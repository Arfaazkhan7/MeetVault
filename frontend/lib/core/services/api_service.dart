import 'dart:convert';
import 'dart:async';
import 'package:flutter/foundation.dart';
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
  String? _refreshToken;

  // Called when authentication fully fails (token expired + refresh failed).
  // AuthProvider registers this during init() to drive navigation to Login.
  VoidCallback? onAuthFailure;

  // Singleton pattern
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString('auth_token');
    _refreshToken = prefs.getString('refresh_token');
    _warmUpBackend();
  }

  void _warmUpBackend() {
    // Fire and forget, silent error handling
    http
        .get(Uri.parse('$baseUrl/health'))
        .timeout(const Duration(seconds: 15))
        .catchError((_) => http.Response('Error', 500));
  }

  Future<void> setToken(String token) async {
    _token = token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', token);
  }

  Future<void> setTokens(String accessToken, String refreshToken) async {
    _token = accessToken;
    _refreshToken = refreshToken;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', accessToken);
    await prefs.setString('refresh_token', refreshToken);
  }

  Future<void> clearToken() async {
    _token = null;
    _refreshToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('refresh_token');
  }

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };

  // ── Auto-refresh logic ────────────────────────────────────────────────────

  bool _isRefreshing = false;

  /// Attempt to refresh the access token using the stored refresh token.
  /// Returns true if a new access token was successfully obtained.
  Future<bool> _tryRefreshToken() async {
    if (_refreshToken == null || _isRefreshing) return false;
    _isRefreshing = true;
    try {
      final response = await http
          .post(
            Uri.parse('$baseUrl/auth/refresh'),
            headers: {'Content-Type': 'application/json'},
            body: json.encode({'refresh_token': _refreshToken}),
          )
          .timeout(const Duration(seconds: 10));

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final newAccess = data['access_token'] as String?;
        final newRefresh = data['refresh_token'] as String?;
        if (newAccess != null) {
          await setTokens(newAccess, newRefresh ?? _refreshToken!);
          debugPrint('[Auth] Token refreshed successfully. '
              'New token length: ${newAccess.length}');
          _isRefreshing = false;
          return true;
        }
      }
      debugPrint('[Auth] Token refresh failed with status ${response.statusCode}');
    } catch (e) {
      debugPrint('[Auth] Token refresh exception: $e');
    }
    _isRefreshing = false;
    return false;
  }

  /// Called when a request returns 401 and refresh also failed (or no refresh
  /// token available). Clears credentials and notifies AuthProvider.
  Future<void> _handleAuthenticationFailure() async {
    debugPrint('[Auth] Authentication failure — clearing tokens and redirecting to login');
    await clearToken();
    onAuthFailure?.call();
  }

  // ── HTTP helpers ──────────────────────────────────────────────────────────

  Future<http.Response> _requestWithRetry(
    Future<http.Response> Function() requestFn, {
    bool allowRefresh = true,
  }) async {
    const maxRetries = 5; // attempt 0, 1, 2, 3, 4
    final backoffs = [1, 2, 4, 8];

    for (int attempt = 0; attempt < maxRetries; attempt++) {
      try {
        final response = await requestFn().timeout(const Duration(seconds: 12));

        // If it's 502, 503, or 504, the backend might be starting up
        if (response.statusCode == 502 ||
            response.statusCode == 503 ||
            response.statusCode == 504) {
          if (attempt < maxRetries - 1) {
            await Future.delayed(Duration(seconds: backoffs[attempt]));
            continue;
          }
        }

        // Handle 401 with automatic token refresh (once)
        if (response.statusCode == 401 && allowRefresh) {
          debugPrint('[Auth] 401 received on attempt $attempt — trying token refresh');
          final refreshed = await _tryRefreshToken();
          if (refreshed) {
            // Retry once with the new access token (no further refresh)
            return await _requestWithRetry(requestFn, allowRefresh: false);
          } else {
            // Refresh also failed — full auth failure
            await _handleAuthenticationFailure();
            throw ApiException(
              message: 'Your session has expired. Please sign in again.',
              statusCode: 401,
            );
          }
        }

        return _handleResponse(response);
      } catch (e) {
        if (e is ApiException) rethrow;
        if (e is TimeoutException ||
            e is http.ClientException ||
            e.toString().contains('SocketException') ||
            e.toString().contains('Failed to fetch')) {
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
    return _requestWithRetry(
      () => http.get(Uri.parse('$baseUrl$endpoint'), headers: _headers),
    );
  }

  Future<http.Response> post(String endpoint,
      {Map<String, dynamic>? body}) async {
    return _requestWithRetry(
      () => http.post(
        Uri.parse('$baseUrl$endpoint'),
        headers: _headers,
        body: body != null ? json.encode(body) : null,
      ),
    );
  }

  Future<http.Response> put(String endpoint,
      {Map<String, dynamic>? body}) async {
    return _requestWithRetry(
      () => http.put(
        Uri.parse('$baseUrl$endpoint'),
        headers: _headers,
        body: body != null ? json.encode(body) : null,
      ),
    );
  }

  Future<http.Response> delete(String endpoint) async {
    return _requestWithRetry(
      () => http.delete(Uri.parse('$baseUrl$endpoint'), headers: _headers),
    );
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
      return data['message']?.toString() ??
          'An error occurred (Status: ${response.statusCode})';
    } catch (e) {
      if (response.statusCode == 502 || response.statusCode == 503) {
        return 'Service is temporarily unavailable. Please try again.';
      }
      return 'An error occurred (Status: ${response.statusCode})';
    }
  }

  bool get isAuthenticated => _token != null;
  String? get token => _token;
  String? get refreshToken => _refreshToken;

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
