import 'package:flutter/material.dart';

class IndustryPage extends StatelessWidget {
  const IndustryPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(backgroundColor: Colors.white, elevation: 0, iconTheme: const IconThemeData(color: Colors.black)),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text("What industry are you\nlooking for today?", 
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 40, fontWeight: FontWeight.bold)),
            const SizedBox(height: 40),
            
            // Search Pill [cite: 78]
            Container(
              width: 600, height: 70,
              padding: const EdgeInsets.symmetric(horizontal: 25),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(35),
                boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 15)],
                border: Border.all(color: Colors.black12)
              ),
              child: Row(
                children: [
                  const Expanded(
                    child: TextField(decoration: InputDecoration(hintText: "Enter industry name", border: InputBorder.none)),
                  ),
                  IconButton(onPressed: () {}, icon: const Icon(Icons.send_rounded))
                ],
              ),
            ),
            const SizedBox(height: 60),
            
            // History Grid [cite: 76, 79, 80, 81]
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _buildCard("1", "Fintech"),
                _buildCard("2", "Agriculture"),
                _buildCard("3", "Real Estate"),
                _buildCard("4", "SMEs"),
              ],
            )
          ],
        ),
      ),
    );
  }

  Widget _buildCard(String number, String label) {
    return Container(
      width: 150, height: 150,
      margin: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(25)),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(number, style: const TextStyle(color: Colors.white, fontSize: 36, fontWeight: FontWeight.w100)),
          Text(label, style: const TextStyle(color: Colors.white60, fontSize: 10)),
        ],
      ),
    );
  }
}