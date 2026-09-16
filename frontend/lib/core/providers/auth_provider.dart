import 'dart:convert';
import 'package:flutter/foundation.dart';
import '../services/api_service.dart';
import '../services/firebase_auth_service.dart';

enum AuthStatus {
  initializing,
  authenticated,
  unauthenticated,
}

class AuthProvider with ChangeNotifier {
  final ApiService _apiService = ApiService();
  final FirebaseAuthService _firebaseAuthService = FirebaseAuthService();

  AuthStatus _status = AuthStatus.initializing;
  bool _isLoading = false;
  String? _errorMessage;
  String? _currentUser;
  String? _userFullName;
  String? _userEmail;
  String? _currentCompanyId;
  String _accountType = 'personal';
  String? _pendingInviteCode;

  AuthStatus get status => _status;
  bool get isInitializing => _status == AuthStatus.initializing;
  bool get isAuthenticated =>
      _status == AuthStatus.authenticated && _currentUser != null;
  bool get isUnauthenticated => _status == AuthStatus.unauthenticated;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  String? get currentUser => _currentUser;
  String? get userFullName => _userFullName;
  String? get userEmail => _userEmail;
  String? get currentCompanyId => _currentCompanyId;
  String get accountType => _accountType;
  bool get isPersonal => _accountType == 'personal';
  bool get isOrganization => _accountType == 'organization';
  String? get pendingInviteCode => _pendingInviteCode;

  set pendingInviteCode(String? code) {
    _pendingInviteCode = code;
    notifyListeners();
  }

  void clearPendingInviteCode() {
    _pendingInviteCode = null;
  }

  String get displayName {
    if (_userFullName != null && _userFullName!.trim().isNotEmpty) {
      return _userFullName!;
    }
    if (_userEmail != null && _userEmail!.contains('@')) {
      final prefix = _userEmail!.split('@')[0];
      return prefix[0].toUpperCase() + prefix.substring(1);
    }
    return _currentUser ?? 'User';
  }

  /// Called by ApiService whenever a 401 is received and automatic token
  /// refresh has also failed. Clears state and notifies listeners so that
  /// the router immediately redirects to the Login screen.
  void handleGlobalAuthFailure() {
    debugPrint('[AuthProvider] handleGlobalAuthFailure — forcing logout');
    _resetUserData();
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  Future<void> init() async {
    _status = AuthStatus.initializing;
    notifyListeners();

    await _apiService.init();

    // Register the global auth failure callback so any 401 (after failed
    // refresh) automatically drives the router back to Login.
    _apiService.onAuthFailure = handleGlobalAuthFailure;

    if (_apiService.isAuthenticated) {
      try {
        final response = await _apiService.get('/auth/me');
        final data = json.decode(response.body);
        _currentUser = data['public_id'] ?? data['id'] ?? 'user';
        _userFullName = data['full_name'];
        _userEmail = data['email'];
        _currentCompanyId = data['company_id'];
        _accountType = data['account_type'] ?? 'personal';
        await _loadCompany();
        _status = AuthStatus.authenticated;
        debugPrint('[Auth] Startup verified. User: ${_currentUser} '
            '(token length: ${_apiService.token?.length ?? 0})');
      } on ApiException catch (e) {
        if (e.statusCode == 401 || e.statusCode == 403) {
          // Token is definitively invalid — clear everything.
          await _apiService.clearToken();
          _resetUserData();
          _status = AuthStatus.unauthenticated;
          debugPrint('[Auth] Startup /auth/me returned ${e.statusCode} — '
              'clearing token, redirecting to login');
        } else {
          // Transient server/network error (503, timeout etc.).
          // ApiService already attempted refresh internally.
          // If we arrive here it means even refresh failed or wasn't applicable.
          // Clear the token to avoid a stuck authenticated-but-broken state.
          await _apiService.clearToken();
          _resetUserData();
          _status = AuthStatus.unauthenticated;
          debugPrint('[Auth] Startup /auth/me failed with ${e.statusCode} — '
              'clearing state, user must re-login');
        }
      } catch (e) {
        await _apiService.clearToken();
        _resetUserData();
        _status = AuthStatus.unauthenticated;
        debugPrint('[Auth] Startup /auth/me unexpected error: $e');
      }
    } else {
      _resetUserData();
      _status = AuthStatus.unauthenticated;
      debugPrint('[Auth] No stored token — unauthenticated');
    }
    notifyListeners();
  }

  void _resetUserData() {
    _currentUser = null;
    _userFullName = null;
    _userEmail = null;
    _currentCompanyId = null;
    _accountType = 'personal';
  }

  Future<bool> login(
    String email,
    String password, {
    String accountType = 'personal',
    String? workspaceCode,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      String endpoint = '/auth/login/personal';
      Map<String, dynamic> body = {
        'email': email,
        'password': password,
      };

      if (accountType == 'organization') {
        endpoint = '/auth/login/workspace';
        body['workspace_code'] = workspaceCode;
      }

      final response = await _apiService.post(endpoint, body: body);

      final data = json.decode(response.body);
      final accessToken = data['access_token'] as String;
      final refreshToken = data['refresh_token'] as String?;

      // Store BOTH tokens
      if (refreshToken != null) {
        await _apiService.setTokens(accessToken, refreshToken);
        debugPrint('[Auth] Login stored access token (length: ${accessToken.length}) '
            'and refresh token (length: ${refreshToken.length})');
      } else {
        await _apiService.setToken(accessToken);
        debugPrint('[Auth] Login stored access token (length: ${accessToken.length}) '
            '— no refresh token in response');
      }

      final meResponse = await _apiService.get('/auth/me');
      final me = json.decode(meResponse.body);
      _currentUser = me['public_id'] ?? me['id'] ?? 'user';
      _userFullName = me['full_name'];
      _userEmail = me['email'];
      _currentCompanyId = me['company_id'];
      _accountType = accountType;

      if (accountType == 'organization') {
        if (data.containsKey('workspace_id')) {
          _currentCompanyId = data['workspace_id'];
        }
        _apiService.companyId = _currentCompanyId;
      } else {
        _currentCompanyId = null;
        _apiService.companyId = null;
      }

      _status = AuthStatus.authenticated;
      _isLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e.toString();
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  Future<bool> loginWithGoogle() async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final idToken =
          await _firebaseAuthService.signInWithGoogleAndGetIdToken();
      await _finishGoogleBackendLogin(idToken);
      _status = AuthStatus.authenticated;
      _isLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = _friendlyGoogleError(e);
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  Future<bool> registerWithGoogle() => loginWithGoogle();

  Future<bool> register(
    String email,
    String password,
    String fullName, {
    String accountType = 'personal',
    String? organizationName,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      await _apiService.post('/auth/register', body: {
        'email': email,
        'password': password,
        'full_name': fullName,
        'account_type': accountType,
        'organization_name': organizationName,
      });

      final loginResponse = await _apiService.post('/auth/login', body: {
        'email': email,
        'password': password,
      });
      final data = json.decode(loginResponse.body);
      final accessToken = data['access_token'] as String;
      final refreshToken = data['refresh_token'] as String?;
      if (refreshToken != null) {
        await _apiService.setTokens(accessToken, refreshToken);
      } else {
        await _apiService.setToken(accessToken);
      }

      final meResponse = await _apiService.get('/auth/me');
      final me = json.decode(meResponse.body);
      _currentUser = me['public_id'] ?? me['id'] ?? 'user';
      _userFullName = me['full_name'];
      _userEmail = me['email'];
      _accountType = accountType;

      if (accountType == 'organization') {
        await _loadCompany();
      } else {
        _currentCompanyId = null;
        _apiService.companyId = null;
      }

      _status = AuthStatus.authenticated;
      _isLoading = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e.toString();
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> logout() async {
    await _firebaseAuthService.signOut();
    await _apiService.clearToken();
    _resetUserData();
    _status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  String _friendlyGoogleError(Object error) {
    final message = error.toString();
    if (error is ApiException) {
      if (error.statusCode == 401) {
        return 'Google account was accepted by Firebase, but MeetVault could not verify it. Please try again in a moment.';
      }
      if (error.statusCode == 403 || error.statusCode == 503) {
        return error.message;
      }
      return 'MeetVault backend rejected Google sign-in: ${error.message}';
    }
    if (message.contains('operation-not-allowed')) {
      return 'Google sign-in is disabled. Enable Google under Firebase Authentication > Sign-in method.';
    }
    if (message.contains('unauthorized-domain')) {
      return 'This website is not authorized for Google sign-in. Add ai-meet-f8fd0.web.app under Firebase Authentication > Settings > Authorized domains.';
    }
    if (message.contains('popup-blocked')) {
      return 'Your browser blocked the Google sign-in popup. Allow popups for this site and try again.';
    }
    if (message.contains('invalid-api-key') ||
        message.contains('api-key-not-valid')) {
      return 'The Firebase API key is invalid. Update the FIREBASE_API_KEY GitHub secret and redeploy.';
    }
    if (message.contains('account-exists-with-different-credential')) {
      return 'An account already exists with this email. Sign in with the original provider.';
    }
    if (message.contains('popup-closed-by-user')) {
      return 'Google sign-in was closed before it finished.';
    }
    if (message.contains('network-request-failed')) {
      return 'Network problem during Google sign-in. Please check your connection.';
    }
    if (message.contains('FIREBASE_API_KEY')) {
      return 'Google sign-in is not configured yet. Add FIREBASE_API_KEY during the Flutter build.';
    }
    return 'Google sign-in failed. Please try again.';
  }

  Future<void> _finishGoogleBackendLogin(String idToken) async {
    final response = await _apiService.post('/auth/firebase/google', body: {
      'id_token': idToken,
    });
    final data = json.decode(response.body);
    final accessToken = data['access_token'] as String;
    final refreshToken = data['refresh_token'] as String?;
    if (refreshToken != null) {
      await _apiService.setTokens(accessToken, refreshToken);
    } else {
      await _apiService.setToken(accessToken);
    }

    final meResponse = await _apiService.get('/auth/me');
    final me = json.decode(meResponse.body);
    _currentUser = me['public_id'] ?? me['id'] ?? 'user';
    _userFullName = me['full_name'];
    _userEmail = me['email'];
    _currentCompanyId = null;
    _accountType = 'personal';
    _apiService.companyId = null;
  }

  Future<void> _loadCompany() async {
    try {
      final response = await _apiService.get('/companies');
      final companies =
          List<Map<String, dynamic>>.from(json.decode(response.body) as List);
      if (companies.isNotEmpty) {
        _currentCompanyId = companies[0]['public_id'];
        _apiService.companyId = _currentCompanyId;
      } else {
        final createRes = await _apiService.post('/companies', body: {
          'name': 's Workspace',
        });
        if (createRes.statusCode == 201) {
          final compData = json.decode(createRes.body);
          _currentCompanyId = compData['public_id'];
          _apiService.companyId = _currentCompanyId;
        }
      }
    } catch (_) {
      // No company yet
    }
  }

  void clearError() {
    _errorMessage = null;
    notifyListeners();
  }
}
