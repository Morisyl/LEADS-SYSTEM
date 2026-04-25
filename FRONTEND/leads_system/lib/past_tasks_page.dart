import 'package:flutter/material.dart';
import 'main.dart'; // Access DatabaseHelper

class PastTasksPage extends StatefulWidget {
  const PastTasksPage({super.key});

  @override
  State<PastTasksPage> createState() => _PastTasksPageState();
}

class _PastTasksPageState extends State<PastTasksPage> {
  List<Map<String, dynamic>> _allTasks = [];

  @override
  void initState() {
    super.initState();
    _fetchHistory();
  }

  Future<void> _fetchHistory() async {
    final db = await DatabaseHelper.instance.database;
    final results = await db.query('tasks', orderBy: 'id DESC');
    setState(() => _allTasks = results);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        title: const Text("PAST TASKS PAGE", style: TextStyle(fontWeight: FontWeight.bold, color: Colors.black)),
        backgroundColor: Colors.white,
        elevation: 0,
        iconTheme: const IconThemeData(color: Colors.black),
      ),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: ListView.builder(
          itemCount: _allTasks.length,
          itemBuilder: (context, index) {
            final task = _allTasks[index];
            return Container(
              margin: const EdgeInsets.symmetric(vertical: 10),
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(25)),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(flex: 2, child: Text(task['project_name'], style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold))),
                  Expanded(flex: 3, child: Text(task['industry'] ?? "General", style: const TextStyle(color: Colors.white70, fontSize: 12))),
                  const Text("2026-04-17", style: TextStyle(color: Colors.white38, fontSize: 10)), // Static for now
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}