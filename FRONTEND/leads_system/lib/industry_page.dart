import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'results_page.dart';

class IndustryPage extends StatefulWidget {
  const IndustryPage({super.key});

  @override
  State<IndustryPage> createState() => _IndustryPageState();
}

class _IndustryPageState extends State<IndustryPage> {
  final TextEditingController _searchController = TextEditingController();
  List<String> _recentIndustries = [];
  final String _baseUrl = "http://localhost:8000";
  final String _apiKey = "jkuat_secret_2026";

  static const List<String> _defaultIndustries = [
    'Solar',
    'Construction',
    'Technology',
    'Manufacturing',
  ];

  @override
  void initState() {
    super.initState();
    _loadRecentIndustries();
  }

  Future<void> _loadRecentIndustries() async {
    // Load available industries from backend
    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/leads/industries'),
        headers: {'X-API-KEY': _apiKey},
      );
      if (response.statusCode == 200) {
        final industries = List<String>.from(jsonDecode(response.body));
        setState(() {
          _recentIndustries = industries.take(4).toList();
        });
      }
    } catch (e) {
      // Fall back to defaults if API fails
      setState(() {
        _recentIndustries = _defaultIndustries;
      });
    }
  }

  Future<void> _searchIndustry(String industry) async {
    if (industry.trim().isEmpty) return;

    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/leads/by-industry/${Uri.encodeComponent(industry)}'),
        headers: {'X-API-KEY': _apiKey},
      );

      if (response.statusCode == 200) {
        final leads = List<Map<String, dynamic>>.from(
          jsonDecode(response.body).map((e) => Map<String, dynamic>.from(e))
        );

        if (!mounted) return;

        if (leads.isEmpty) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text('No leads found for "$industry"'),
              backgroundColor: Colors.orange,
            ),
          );
          return;
        }

        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => ResultsPage(
              taskId: 'industry-${industry.toLowerCase()}',
              taskName: '$industry Industry Leads',
              pendingReview: false,
              preloadedLeads: leads,
            ),
          ),
        );
      } else {
        _showError('Failed to load leads: ${response.statusCode}');
      }
    } catch (e) {
      _showError('Search error: $e');
    }
  }

  void _showError(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: Colors.red),
    );
  }

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
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              "What industry are you\nlooking for today?",
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 40, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 40),

            // Search Pill
            Container(
              width: 600,
              height: 70,
              padding: const EdgeInsets.symmetric(horizontal: 25),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(35),
                boxShadow: const [
                  BoxShadow(color: Colors.black12, blurRadius: 15)
                ],
                border: Border.all(color: Colors.black12),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _searchController,
                      decoration: const InputDecoration(
                        hintText: "Enter industry name",
                        border: InputBorder.none,
                      ),
                      onSubmitted: _searchIndustry,
                    ),
                  ),
                  IconButton(
                    onPressed: () => _searchIndustry(_searchController.text),
                    icon: const Icon(Icons.send_rounded),
                  )
                ],
              ),
            ),
            const SizedBox(height: 60),

            // History Grid
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                for (int i = 0; i < 4; i++)
                  _buildCard(
                    "${i + 1}",
                    i < _recentIndustries.length
                        ? _recentIndustries[i]
                        : _defaultIndustries[i],
                  ),
              ],
            )
          ],
        ),
      ),
    );
  }

  Widget _buildCard(String number, String label) {
    return GestureDetector(
      onTap: () => _searchIndustry(label),
      child: Container(
        width: 150,
        height: 150,
        margin: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Colors.black,
          borderRadius: BorderRadius.circular(25),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              number,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 36,
                fontWeight: FontWeight.w100,
              ),
            ),
            Text(
              label,
              style: const TextStyle(color: Colors.white60, fontSize: 10),
            ),
          ],
        ),
      ),
    );
  }
}