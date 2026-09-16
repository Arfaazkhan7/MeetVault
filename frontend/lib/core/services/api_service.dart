import 'dart:convert';
import 'dart:async';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    // Production-safe fallback for hosted/mobile builds. Local development
    // passes --dart-define=API_BASE_URL=http://localhost:8000/api/v1.
    defaultValue: 'https://meetvault-api.onrender.com/api/v1',
  );
  String? _token;
  
  // Singleton pattern
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();
  
  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('auth_token');
    _warmUpBackend();
  }

  void _warmUpBackend() {
    // Fire and forget, silent error handling
    http.get(Uri.parse('$baseUrl/health')).timeout(const Duration(seconds: 15)).catchError((_) => http.Response('Error', 500));
  }
  
  Future<void> setToken(String token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', token);
  }
  
  Future<void> clearToken() async {
    _token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
  }
  
  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };
  
  Future<http.Response> _requestWithRetry(Future<http.Response> Function() requestFn) async {
    const maxRetries = 5; // attempt 0, 1, 2, 3, 4
    final backoffs = [1, 2, 4, 8];
    
    for (int attempt = 0; attempt < maxRetries; attempt++) {
      try {
        final response = await requestFn().timeout(const Duration(seconds: 12));
        
        // If it's 502, 503, or 504, the backend might be starting up
        if (response.statusCode == 502 || response.statusCode == 503 || response.statusCode == 504) {
          if (attempt < maxRetries - 1) {
            await Future.delayed(Duration(seconds: backoffs[attempt]));
            continue;
          }
        }
        
        return _handleResponse(response);
      } catch (e) {
        if (e is TimeoutException || e is http.ClientException || e.toString().contains('SocketException') || e.toString().contains('Failed to fetch')) {
          if (attempt < maxRetries - 1) {
            await Future.delayed(Duration(seconds: backoffs[attempt]));
            continue;
          }
          throw ApiException(
            message: 'Service is temporarily unavailable. Please try again.',
            statusCode: 503,
          );
        }
        rethrow;
      }
    }
    
    throw ApiException(
      message: 'Service is temporarily unavailable. Please try again.',
      statusCode: 503,
    );
  }
  
  Future<http.Response> get(String endpoint) async {
    return _requestWithRetry(() => http.get(
      Uri.parse('$baseUrl$endpoint'),
      headers: _headers,
    ));
  }
  
  Future<http.Response> post(String endpoint, {Map<String, dynamic>? body}) async {
    return _requestWithRetry(() => http.post(
      Uri.parse('$baseUrl$endpoint'),
      headers: _headers,
      body: body != null ? json.encode(body) : null,
    ));
  }
  
  Future<http.Response> put(String endpoint, {Map<String, dynamic>? body}) async {
    return _requestWithRetry(() => http.put(
      Uri.parse('$baseUrl$endpoint'),
      headers: _headers,
      body: body != null ? json.encode(body) : null,
    ));
  }
  
  Future<http.Response> delete(String endpoint) async {
    return _requestWithRetry(() => http.delete(
      Uri.parse('$baseUrl$endpoint'),
      headers: _headers,
    ));
  }
  
  http.Response _handleResponse(http.Response response) {
    if (response.statusCode >= 400) {
      throw ApiException(
        message: _getErrorMessage(response),
        statusCode: response.statusCode,
      );
    }
    return response;
  }
  
  String _getErrorMessage(http.Response response) {
    try {
      final data = json.decode(response.body);
      if (data['detail'] != null) {
        if (data['detail'] is List) {
          final list = data['detail'] as List;
          return list.map((e) {
            if (e is Map && e.containsKey('msg')) {
              String msg = e['msg'].toString();
              if (msg.startsWith('Value error, ')) {
                msg = msg.replaceFirst('Value error, ', '');
              }
              return msg;
            }
            return e.toString();
          }).join('\n');
        }
        return data['detail'].toString();
      }
      return data['message']?.toString() ?? 'An error occurred (Status: ${response.statusCode})';
    } catch (e) {
      if (response.statusCode == 502 || response.statusCode == 503) {
         return 'Service is temporarily unavailable. Please try again.';
      }
      return 'An error occurred (Status: ${response.statusCode})';
    }
  }
  
  bool get isAuthenticated => _token != null;
  String? get token => _token;

  String? _companyId;
  String? get companyId => _companyId;
  set companyId(String? value) => _companyId = value;
}

class ApiException implements Exception {
  final String message;
  final int statusCode;
  
  ApiException({required this.message, required this.statusCode});
  
  @override
  String toString() => message;
}
