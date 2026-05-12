import 'package:flutter/material.dart';

AppBar buildCustomAppBar(BuildContext context, String title) {
  return AppBar(
    backgroundColor: Color(0xFF6BCF47),
    title: Text(title, style: TextStyle(color: Colors.white)),
    leading: IconButton(
      icon: Icon(Icons.home, color: Colors.white),
      onPressed: () {
        // Navigate back to home, removing all routes
        Navigator.of(context).popUntil((route) => route.isFirst);
      },
    ),
  );
}