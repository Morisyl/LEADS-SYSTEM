import 'dart:math';
import 'dart:io';
import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:http/http.dart' as http;

// Internal Pages
import 'execution_page.dart';
import 'industry_page.dart';
import 'past_tasks_page.dart';

// ==========================================
// 0. ENTRY POINT & APP WRAPPER
// ==========================================
void main() {
  // Required for database support on Windows/macOS desktop
  sqfliteFfiInit();
  databaseFactory = databaseFactoryFfi;
  
  runApp(const EnolixApp());
}

class EnolixApp extends StatelessWidget {
  const EnolixApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Enolix B2B Orchestrator V3',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFFF8F9FA),
        fontFamily: 'GoogleSans', // Matches your JKUAT project aesthetic
      ),
      home: const HomePage(),
    );
  }
}

// ==========================================
// 1. DATABASE HELPER (V3 COMPATIBLE)
// ==========================================
class DatabaseHelper {
  static final DatabaseHelper instance = DatabaseHelper._init();
  static Database? _database;
  DatabaseHelper._init();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB('enolix_v3.db');
    return _database!;
  }

  Future<Database> _initDB(String filePath) async {
    // CHANGE THIS LINE: use getApplicationSupportDirectory instead of Documents
    final appDir = await getApplicationSupportDirectory(); 
    final path = p.join(appDir.path, filePath);

    print("🚀 TRYING NEW PATH: $path");

    final dbFolder = Directory(p.dirname(path));
    if (!await dbFolder.exists()) {
      await dbFolder.create(recursive: true);
    }

    return await databaseFactoryFfi.openDatabase(path,
        options: OpenDatabaseOptions(
          version: 1,
          onCreate: (db, version) async {
            await db.execute('''
              CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                industry TEXT,
                status TEXT
              )
            ''');
          },
        ));
  }

  Future<int> insertTask(String taskId, String projectName, String industry) async {
    final db = await instance.database;
    return await db.insert('tasks', {
      'task_id': taskId,
      'project_name': projectName,
      'industry': industry,
      'status': 'Processing',
    });
  }

  Future<List<Map<String, dynamic>>> getRecentTasks() async {
    final db = await instance.database;
    return await db.query('tasks', orderBy: 'id DESC', limit: 3);
  }
}

// ==========================================
// 2. MAIN PAGE IMPLEMENTATION
// ==========================================
class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final TextEditingController _promptController = TextEditingController();
  List<PlatformFile> _attachedFiles = [];
  List<Map<String, dynamic>> _recentTasks = [];
  late String _greeting;
  
  // Backend Configuration (Must match main.py)
  final String _baseUrl = "http://localhost:8000";
  final String _apiKey = "jkuat_secret_2026";

  final List<String> _greetingsPool = [
    "Where shall we start?", "What's our objective today?", "Ready for data extraction.",
    "Initiating workflow...", "System online. What's next?", "Enter target parameters.",
    "Ready to scrape.", "What are we researching?", "Data harvest ready."
  ];

  @override
  void initState() {
    super.initState();
    _greeting = _greetingsPool[Random().nextInt(_greetingsPool.length)];
    _promptController.addListener(() => setState(() {}));
    _loadRecentTasks();
  }

  Future<void> _loadRecentTasks() async {
    final tasks = await DatabaseHelper.instance.getRecentTasks();
    setState(() => _recentTasks = tasks);
  }

  Future<void> _pickFiles() async {
    FilePickerResult? result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf', 'jpg', 'png'],
    );
    if (result != null) {
      setState(() => _attachedFiles = result.files);
    }
  }

  Future<void> _initiateWorkflow(String projectName) async {
    String? taskId;
    String industry = "General";

    try {
      http.Response response;
      
      if (_attachedFiles.isNotEmpty) {
        // Multi-part upload logic...
        var request = http.MultipartRequest('POST', Uri.parse('$_baseUrl/upload'));
        request.headers['X-API-KEY'] = _apiKey;
        request.files.add(await http.MultipartFile.fromPath('file', _attachedFiles.first.path!));
        var streamedResponse = await request.send();
        response = await http.Response.fromStream(streamedResponse);
      } else {
        // URL or Prompt Search
        response = await http.get(
          Uri.parse('$_baseUrl/search-listings?prompt=${Uri.encodeComponent(_promptController.text)}&industry=$industry'),
          headers: {'X-API-KEY': _apiKey},
        );
      }

      // DIAGNOSTIC CHECK
      if (response.statusCode == 200) {
        taskId = jsonDecode(response.body)['task_id'];
      } else {
        // This will tell us if it's 403 (Auth), 500 (Server Error), or 404
        throw Exception("Backend Error ${response.statusCode}: ${response.body}");
      }

      if (taskId != null) {
        await DatabaseHelper.instance.insertTask(taskId, projectName, industry);
        _promptController.clear();
        setState(() => _attachedFiles.clear());
        _loadRecentTasks();
        
        if (!mounted) return;
        Navigator.push(context, MaterialPageRoute(
          builder: (context) => ExecutionPage(taskId: taskId!, promptOrUrl: projectName),
        ));
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('❌ System Start Failed: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }

  void _showNamingPopup() {
    final nameController = TextEditingController();
    showDialog(
      context: context,
      builder: (context) => Dialog(
        backgroundColor: Colors.transparent,
        child: Container(
          width: 400,
          padding: const EdgeInsets.all(30),
          decoration: BoxDecoration(
            color: Colors.black.withValues(alpha: 0.9),
            borderRadius: BorderRadius.circular(25),
            border: Border.all(color: Colors.white24),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text("Name this Task", style: TextStyle(color: Colors.white, fontSize: 18)),
              const SizedBox(height: 20),
              TextField(
                controller: nameController,
                autofocus: true,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  hintText: "e.g., Nairobi SME Outreach",
                  hintStyle: TextStyle(color: Colors.white38),
                  enabledBorder: UnderlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
                ),
              ),
              const SizedBox(height: 30),
              TextButton(
                onPressed: () {
                  String name = nameController.text.isEmpty ? "Untitled Task" : nameController.text;
                  Navigator.pop(context);
                  _initiateWorkflow(name);
                },
                child: const Text("START SYSTEM", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
              )
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    bool canSend = _promptController.text.trim().isNotEmpty || _attachedFiles.isNotEmpty;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // BROWSE BUTTON [cite: 1]
            Align(
              alignment: Alignment.topLeft,
              child: Padding(
                padding: const EdgeInsets.all(20.0),
                child: ElevatedButton(
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (context) => const IndustryPage())),
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.black),
                  child: const Text("BROWSE INDUSTRY LEADS", style: TextStyle(color: Colors.white, fontSize: 10)),
                ),
              ),
            ),

            // GREETING [cite: 4-5]
            Expanded(
              flex: 2,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  const Text("Hi!", style: TextStyle(fontSize: 80, fontWeight: FontWeight.w200, letterSpacing: -2)),
                  TypewriterText(
                    text: _greeting,
                    style: const TextStyle(fontSize: 42, fontWeight: FontWeight.bold, color: Colors.black87),
                  ),
                  const SizedBox(height: 40),
                ],
              ),
            ),

            // SEARCH PILL [cite: 3, 6]
            // MIDDLE: Search Pill & Add Button
            // MIDDLE: Search Pill & Add Button
            Expanded(
              flex: 1,
              child: SingleChildScrollView(  // ADD THIS WRAPPER
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        // Plus Button (Detached Circle)
                        GestureDetector(
                          onTap: _pickFiles,
                          child: Container(
                            width: 75, height: 75,
                            decoration: const BoxDecoration(color: Colors.black, shape: BoxShape.circle),
                            child: Icon(Icons.add, color: _attachedFiles.isNotEmpty ? Colors.greenAccent : Colors.white, size: 35),
                          ),
                        ),
                        const SizedBox(width: 25),
                        // Input Pill
                        Container(
                          width: 600, height: 75,
                          padding: const EdgeInsets.symmetric(horizontal: 25),
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(40),
                            boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 20, offset: Offset(0, 10))],
                          ),
                          child: Row(
                            children: [
                              Expanded(
                                child: TextField(
                                  controller: _promptController,
                                  style: const TextStyle(fontSize: 20),
                                  decoration: const InputDecoration(hintText: "Enter prompt or url", border: InputBorder.none),
                                ),
                              ),
                              IconButton(
                                onPressed: canSend ? _showNamingPopup : null,
                                icon: Icon(Icons.send_rounded, color: canSend ? Colors.black : Colors.grey),
                              )
                            ],
                          ),
                        ),
                      ],
                    ),

                    // NEW: Visual File Preview Chip
                    if (_attachedFiles.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 15.0),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 8),
                          decoration: BoxDecoration(
                            color: Colors.greenAccent.withValues(alpha: 0.1),
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.5)),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Icon(Icons.description, size: 18, color: Colors.green),
                              const SizedBox(width: 8),
                              Text(
                                _attachedFiles.first.name, 
                                style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.black87)
                              ),
                              const SizedBox(width: 8),
                              GestureDetector(
                                onTap: () => setState(() => _attachedFiles.clear()),
                                child: const Icon(Icons.close, size: 18, color: Colors.redAccent),
                              ),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
              ),  // ADD THIS CLOSING PARENTHESIS FOR SingleChildScrollView
            ),

            // TASK TILES [cite: 7-12]
            Expanded(
              flex: 2,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (int i = 0; i < 3; i++) 
                    _buildTaskTile(i < _recentTasks.length ? _recentTasks[i] : null, i + 1),
                  _buildFolderTile(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTaskTile(Map? task, int index) {
    return Container(
      margin: const EdgeInsets.all(15),
      width: 180, height: 180,
      decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(35)),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text("$index", style: const TextStyle(color: Colors.white, fontSize: 50, fontWeight: FontWeight.w100)),
          if (task != null)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10),
              child: Text(task['project_name'], 
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white60, fontSize: 12), 
                maxLines: 2, overflow: TextOverflow.ellipsis),
            )
        ],
      ),
    );
  }

  Widget _buildFolderTile() {
    return GestureDetector(
      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (context) => const PastTasksPage())),
      child: Container(
        margin: const EdgeInsets.all(15),
        width: 180, height: 180,
        decoration: BoxDecoration(color: Colors.grey[300], borderRadius: BorderRadius.circular(35)),
        child: const Icon(Icons.folder_open_rounded, size: 60, color: Colors.black45),
      ),
    );
  }
}

// ==========================================
// 3. TYPEWRITER ANIMATION HELPER
// ==========================================
class TypewriterText extends StatefulWidget {
  final String text;
  final TextStyle style;
  
  // Adding a unique Key forces the widget to rebuild entirely when the text changes
  const TypewriterText({super.key, required this.text, required this.style});

  @override
  State<TypewriterText> createState() => _TypewriterTextState();
}

class _TypewriterTextState extends State<TypewriterText> {
  String _displayedText = "";
  int _currentIndex = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _displayedText = ""; // Ensure it starts empty
    _currentIndex = 0;
    _startTyping();
  }

  // This ensures that if the greeting changes, the animation restarts
  @override
  void didUpdateWidget(TypewriterText oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.text != widget.text) {
      _timer?.cancel();
      setState(() {
        _displayedText = "";
        _currentIndex = 0;
      });
      _startTyping();
    }
  }

  void _startTyping() {
    _timer = Timer.periodic(const Duration(milliseconds: 50), (timer) {
      if (!mounted) return;
      if (_currentIndex < widget.text.length) {
        setState(() {
          _currentIndex++;
          _displayedText = widget.text.substring(0, _currentIndex);
        });
      } else {
        _timer?.cancel();
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Text(_displayedText, style: widget.style);
  }
}