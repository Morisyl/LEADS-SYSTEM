import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

class ResultsPage extends StatefulWidget {
  final String taskId;
  final String taskName;
  final bool pendingReview;
  final List<Map<String, dynamic>>? preloadedLeads; // inline from poll

  const ResultsPage({
    Key? key,
    required this.taskId,
    required this.taskName,
    this.pendingReview   = false,
    this.preloadedLeads,
  }) : super(key: key);

  @override
  State<ResultsPage> createState() => _ResultsPageState();
}

class _ResultsPageState extends State<ResultsPage> {
  List<Map<String, dynamic>> _leads = [];
  bool _isLoading   = true;
  bool _isConfirming = false;

  final String _baseUrl = "http://localhost:8000";
  final String _apiKey  = "jkuat_secret_2026";

  // ── classification options ──────────────────────────────────
  static const List<String> _industries = [
    'General', 'Solar', 'Construction', 'Technology', 'Manufacturing',
    'Healthcare', 'Finance', 'Retail', 'Education', 'Logistics', 'Other',
  ];
  static const List<String> _regions = [
    '', 'Africa', 'Asia', 'Europe', 'Middle East',
    'North America', 'South America', 'Oceania', 'Global',
  ];

  // Bulk-assign state
  String _bulkIndustry = 'General';
  String _bulkRegion   = '';

  @override
  void initState() {
    super.initState();
    if (widget.preloadedLeads != null && widget.preloadedLeads!.isNotEmpty) {
      // Data arrived inline with the status poll — skip the /pending round-trip.
      _leads     = widget.preloadedLeads!;
      _isLoading = false;
    } else {
      _fetchLeads();
    }
  }

  Future<void> _fetchLeads() async {
    final endpoint = widget.pendingReview
        ? '$_baseUrl/tasks/${widget.taskId}/pending'
        : '$_baseUrl/tasks/${widget.taskId}/leads';
    try {
      final response = await http.get(
        Uri.parse(endpoint),
        headers: {'X-API-KEY': _apiKey},
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as List<dynamic>;
        setState(() {
          _leads = data.map((e) => Map<String, dynamic>.from(e as Map)).toList();
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
      }
    } catch (e) {
      debugPrint('Fetch error: $e');
      setState(() => _isLoading = false);
    }
  }

  // ── bulk apply ──────────────────────────────────────────────
  void _applyBulk() {
    setState(() {
      for (final lead in _leads) {
        if (_bulkIndustry.isNotEmpty) lead['industry'] = _bulkIndustry;
        if (_bulkRegion.isNotEmpty)   lead['region']   = _bulkRegion;
      }
    });
  }

  // ── confirm → POST /confirm ─────────────────────────────────
  Future<void> _confirm() async {
    setState(() => _isConfirming = true);
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/tasks/${widget.taskId}/confirm'),
        headers: {'X-API-KEY': _apiKey, 'Content-Type': 'application/json'},
        body: jsonEncode({'leads': _leads}),
      );
      if (response.statusCode == 200) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✓ ${_leads.length} leads saved.'),
            backgroundColor: Colors.green,
          ),
        );
        // Transition: mark as no longer pending so export bar appears
        setState(() => _isConfirming = false);
      } else {
        _showError('Confirm failed: ${response.statusCode}');
      }
    } catch (e) {
      _showError('Confirm error: $e');
    } finally {
      setState(() => _isConfirming = false);
    }
  }

  // ── export ──────────────────────────────────────────────────
  Future<void> _handleExport(String format) async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Row(children: [
          const SizedBox(width: 20, height: 20,
              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
          const SizedBox(width: 16),
          Text('Generating $format file...'),
        ]),
        duration: const Duration(seconds: 2),
      ));
      final response = await http.get(
        Uri.parse('$_baseUrl/savefile?task_id=${widget.taskId}&format=$format'),
        headers: {'X-API-KEY': _apiKey},
      );
      if (response.statusCode == 200) {
        final directory = await getDownloadsDirectory();
        final timestamp = DateTime.now().toIso8601String().substring(0, 19).replaceAll(':', '-');
        final shortId   = widget.taskId.substring(0, 8);
        final filename  = 'leads_export_${timestamp}_$shortId.$format';
        final file      = File('${directory!.path}/$filename');
        await file.writeAsBytes(response.bodyBytes);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('✓ Saved: $filename'),
          backgroundColor: Colors.green,
          duration: const Duration(seconds: 3),
        ));
      } else {
        _showError('Export failed: ${response.statusCode}');
      }
    } catch (e) {
      _showError('Export error. Check console.');
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.red),
    );
  }

  // ── build ───────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.black),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: Text(
          widget.taskName,
          style: const TextStyle(color: Colors.black, fontSize: 18),
        ),
      ),
      body: Stack(
        children: [
          Padding(
            padding: const EdgeInsets.all(40.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const SizedBox(height: 12),

                // ── bulk classification bar ─────────────────
                if (widget.pendingReview) ...[
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    decoration: BoxDecoration(
                      color: Colors.grey[100],
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.black12),
                    ),
                    child: Row(
                      children: [
                        const Text('Bulk assign:',
                            style: TextStyle(fontWeight: FontWeight.bold)),
                        const SizedBox(width: 16),
                        _buildDropdown('Industry', _industries, _bulkIndustry,
                            (v) => setState(() => _bulkIndustry = v!)),
                        const SizedBox(width: 12),
                        _buildDropdown('Region', _regions, _bulkRegion,
                            (v) => setState(() => _bulkRegion = v!)),
                        const SizedBox(width: 12),
                        ElevatedButton(
                          style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.black,
                              foregroundColor: Colors.white),
                          onPressed: _applyBulk,
                          child: const Text('Apply to all'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                ],

                // ── table ───────────────────────────────────
                Expanded(
                  child: Container(
                    decoration: BoxDecoration(
                      border: Border.all(color: Colors.black12),
                      borderRadius: BorderRadius.circular(15),
                    ),
                    child: _isLoading
                        ? const Center(child: CircularProgressIndicator(color: Colors.black))
                        : _leads.isEmpty
                            ? Center(
                                child: Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    Icon(Icons.inbox_outlined,
                                        size: 64, color: Colors.grey[400]),
                                    const SizedBox(height: 16),
                                    Text('No leads found.',
                                        style: TextStyle(
                                            fontSize: 16, color: Colors.grey[600])),
                                  ],
                                ))
                            : Column(
                                children: [
                                  // stats bar
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                        vertical: 12, horizontal: 20),
                                    color: Colors.grey[100],
                                    child: Row(children: [
                                      Text('Total: ${_leads.length}',
                                          style: const TextStyle(
                                              fontWeight: FontWeight.bold,
                                              fontSize: 14)),
                                    ]),
                                  ),
                                  // scrollable table
                                  Expanded(
                                    child: SingleChildScrollView(
                                      scrollDirection: Axis.vertical,
                                      child: SingleChildScrollView(
                                        scrollDirection: Axis.horizontal,
                                        child: DataTable(
                                          headingRowColor:
                                              MaterialStateProperty.all(
                                                  Colors.grey[300]),
                                          columns: [
                                            const DataColumn(label: Text('No.')),
                                            const DataColumn(label: Text('Company')),
                                            const DataColumn(label: Text('Email')),
                                            const DataColumn(label: Text('URL')),
                                            if (widget.pendingReview)
                                              const DataColumn(label: Text('Industry')),
                                            if (widget.pendingReview)
                                              const DataColumn(label: Text('Region')),
                                          ],
                                          rows: List<DataRow>.generate(
                                            _leads.length,
                                            (i) {
                                              final lead = _leads[i];
                                              return DataRow(cells: [
                                                DataCell(Text('${i + 1}')),
                                                DataCell(Text(lead['company'] ??
                                                    lead['company_name'] ?? 'N/A')),
                                                DataCell(Text(lead['email'] ?? 'N/A')),
                                                DataCell(Text(lead['url'] ??
                                                    lead['source_url'] ?? 'N/A')),
                                                if (widget.pendingReview)
                                                  DataCell(_buildDropdown(
                                                    '',
                                                    _industries,
                                                    lead['industry'] ?? 'General',
                                                    (v) => setState(
                                                        () => lead['industry'] = v),
                                                  )),
                                                if (widget.pendingReview)
                                                  DataCell(_buildDropdown(
                                                    '',
                                                    _regions,
                                                    lead['region'] ?? '',
                                                    (v) => setState(
                                                        () => lead['region'] = v),
                                                  )),
                                              ]);
                                            },
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                  ),
                ),
                const SizedBox(height: 100),
              ],
            ),
          ),

          // ── bottom action bar ─────────────────────────────
          Positioned(
            bottom: 40, left: 0, right: 0,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 15),
                decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(50)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (widget.pendingReview) ...[
                      _isConfirming
                          ? const SizedBox(
                              width: 20, height: 20,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white))
                          : ElevatedButton.icon(
                              style: ElevatedButton.styleFrom(
                                  backgroundColor: Colors.greenAccent,
                                  foregroundColor: Colors.black),
                              icon: const Icon(Icons.check),
                              label: const Text('CONFIRM & SAVE'),
                              onPressed: _confirm,
                            ),
                      const SizedBox(width: 20),
                    ],
                    const Text('Export as:',
                        style: TextStyle(color: Colors.white)),
                    const SizedBox(width: 16),
                    _buildExportBtn('PDF', () => _handleExport('pdf')),
                    _buildExportBtn('CSV', () => _handleExport('csv')),
                    _buildExportBtn('TXT', () => _handleExport('txt')),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDropdown(
    String hint,
    List<String> items,
    String value,
    ValueChanged<String?> onChanged,
  ) {
    final safeValue = items.contains(value) ? value : items.first;
    return DropdownButton<String>(
      value: safeValue,
      hint: hint.isNotEmpty ? Text(hint) : null,
      underline: const SizedBox(),
      isDense: true,
      style: const TextStyle(color: Colors.black, fontSize: 13),
      items: items
          .map((e) => DropdownMenuItem(value: e, child: Text(e.isEmpty ? '— region —' : e)))
          .toList(),
      onChanged: onChanged,
    );
  }

  Widget _buildExportBtn(String label, VoidCallback onPressed) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 5),
      child: ElevatedButton(
        style: ElevatedButton.styleFrom(
            backgroundColor: Colors.white,
            foregroundColor: Colors.black,
            shape: const StadiumBorder()),
        onPressed: onPressed,
        child: Text(label),
      ),
    );
  }
}