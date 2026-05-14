import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class AuthService {
  static const String baseUrl = 'http://localhost:8000/api';

  // Singleton
  static final AuthService _instance = AuthService._internal();
  factory AuthService() => _instance;
  AuthService._internal();

  String? _token;
  Map<String, dynamic>? _currentUser;
  
  String? get token => _token;
  Map<String, dynamic>? get currentUser => _currentUser;
  bool get isAuthenticated => _token != null;
  
  Future<bool> login(String username, String password) async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'username': username,
          'password': password,
        }),
      );
      
      final data = jsonDecode(response.body);
      
      if (data['success'] == true) {
        _token = data['user']['token'];
        _currentUser = data['user'];
        
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('auth_token', _token!);
        await prefs.setString('user_data', jsonEncode(_currentUser));
        
        return true;
      }
      return false;
    } catch (e) {
      print('Login error: $e');
      return false;
    }
  }
  
  Future<void> logout() async {
    if (_token != null) {
      try {
        await http.post(
          Uri.parse('$baseUrl/auth/logout'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'token': _token}),
        );
      } catch (e) {
        print('Logout error: $e');
      }
    }
    
    _token = null;
    _currentUser = null;
    
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('user_data');
  }
  
  Future<bool> loadSavedSession() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final savedToken = prefs.getString('auth_token');
      
      if (savedToken == null) return false;
      
      final response = await http.post(
        Uri.parse('$baseUrl/auth/validate'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'token': savedToken}),
      );
      
      final data = jsonDecode(response.body);
      
      if (data['valid'] == true) {
        _token = savedToken;
        _currentUser = data['user'];
        return true;
      } else {
        await logout();
        return false;
      }
    } catch (e) {
      print('Session load error: $e');
      return false;
    }
  }
  
  Map<String, String> getAuthHeaders() {
    return {
      'Content-Type': 'application/json',
      'x-api-key': _token ?? '',
    };
  }
}