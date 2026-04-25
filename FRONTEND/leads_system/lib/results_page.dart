import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

class ResultsPage extends StatefulWidget {
  final String taskId;
  final String taskName;

  const ResultsPage({Key? key, required this.taskId, required this.taskName}) : super(key: key);

  @override
  State<ResultsPage> createState() => _ResultsPageState();
}

class _ResultsPageState extends State<ResultsPage> {
  List<dynamic> _leads = [];
  bool _isLoading = true;
  
  // Export selection state [cite: 55-58]
  bool _exportCompany = true;
  bool _exportUrl = true;
  bool _exportEmail = true;

  final String _baseUrl = "http://localhost:8000";
  final String _apiKey = "jkuat_secret_2026";

  @override
  void initState() {
    super.initState();
    _fetchLeads();
  }

  Future<void> _fetchLeads() async {
    try {
      // We use a custom endpoint or the savefile logic to get raw JSON for the table
      final response = await http.get(
        Uri.parse('$_baseUrl/jobs/${widget.taskId}/status'),
        headers: {'X-API-KEY': _apiKey},
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _leads = data['leads'] ?? []; // Based on V3 logic returning leads in status
          _isLoading = false;
        });
      }
    } catch (e) {
      debugPrint("Fetch error: $e");
    }
  }

  // Trigger Backend File Generation 
  Future<void> _handleExport(String format) async {
    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/savefile?task_id=${widget.taskId}&format=$format'),
        headers: {'X-API-KEY': _apiKey},
      );

      if (response.statusCode == 200) {
        final directory = await getDownloadsDirectory();
        final filePath = '${directory!.path}/${widget.taskName}_export.$format';
        final file = File(filePath);
        await file.writeAsBytes(response.bodyBytes);
        
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Saved to Downloads: ${widget.taskName}_export.$format")),
        );
      }
    } catch (e) {
      debugPrint("Export failed: $e");
    }
  }

  // "FIELDS TO EXPORT" Popup 
  void _showFieldsDialog() {
    showDialog(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => Dialog(
          backgroundColor: Colors.transparent,
          child: Container(
            width: 400,
            padding: const EdgeInsets.all(30),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.9),
              borderRadius: BorderRadius.circular(25),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text("FIELDS TO EXPORT", style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                const SizedBox(height: 20),
                _buildCheckbox("Company name", _exportCompany, (val) => setDialogState(() => _exportCompany = val!)),
                _buildCheckbox("url", _exportUrl, (val) => setDialogState(() => _exportUrl = val!)),
                _buildCheckbox("email", _exportEmail, (val) => setDialogState(() => _exportEmail = val!)),
                const SizedBox(height: 30),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Colors.black),
                  onPressed: () => Navigator.pop(context),
                  child: const Text("OK"),
                )
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Stack(
        children: [
          Padding(
            padding: const EdgeInsets.all(40.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Header [cite: 42]
                Text(widget.taskName, style: const TextStyle(fontSize: 22, decoration: TextDecoration.underline)),
                const SizedBox(height: 30),

                // Table Header & Body 
                Expanded(
                  child: Container(
                    decoration: BoxDecoration(border: Border.all(color: Colors.black12), borderRadius: BorderRadius.circular(15)),
                    child: _isLoading 
                      ? const Center(child: CircularProgressIndicator(color: Colors.black))
                      : SingleChildScrollView(
                          scrollDirection: Axis.vertical,
                          child: DataTable(
                            headingRowColor: MaterialStateProperty.all(Colors.grey[300]),
                            columns: const [
                              DataColumn(label: Text("No.")),
                              DataColumn(label: Text("Company name")),
                              DataColumn(label: Text("url")),
                              DataColumn(label: Text("email")),
                            ],
                            rows: List<DataRow>.generate(
                              _leads.length,
                              (index) => DataRow(cells: [
                                DataCell(Text("${index + 1}")),
                                DataCell(Text(_leads[index]['company_name'] ?? "N/A")),
                                DataCell(Text(_leads[index]['source_url'] ?? "N/A")),
                                DataCell(Text(_leads[index]['email'] ?? "N/A")),
                              ]),
                            ),
                          ),
                        ),
                  ),
                ),
                const SizedBox(height: 100), // Space for floating bar
              ],
            ),
          ),

          // Floating Export Bar 
          Positioned(
            bottom: 40,
            left: 0,
            right: 0,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(50)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text("Export as:", style: TextStyle(color: Colors.white)),
                    const SizedBox(width: 20),
                    _buildExportBtn("PDF", () => _handleExport("pdf")),
                    _buildExportBtn("CSV", () => _handleExport("csv")),
                    _buildExportBtn("TXT", () => _handleExport("txt")),
                    const SizedBox(width: 20),
                    // Gear/Settings icon to trigger Fields Dialog
                    IconButton(
                      icon: const Icon(Icons.settings, color: Colors.white70),
                      onPressed: _showFieldsDialog,
                    )
                  ],
                ),
              ),
            ),
          )
        ],
      ),
    );
  }

  Widget _buildExportBtn(String label, VoidCallback onPressed) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 5),
      child: ElevatedButton(
        style: ElevatedButton.styleFrom(backgroundColor: Colors.white, foregroundColor: Colors.black, shape: const StadiumBorder()),
        onPressed: onPressed,
        child: Text(label),
      ),
    );
  }

  Widget _buildCheckbox(String label, bool value, Function(bool?) onChanged) {
    return Theme(
      data: ThemeData(unselectedWidgetColor: Colors.white),
      child: CheckboxListTile(
        title: Text(label, style: const TextStyle(color: Colors.white)),
        value: value,
        onChanged: onChanged,
        controlAffinity: ListTileControlAffinity.leading,
      ),
    );
  }
}