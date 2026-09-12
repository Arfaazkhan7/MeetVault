import 'dart:convert';
import 'package:flutter/foundation.dart';
import '../services/api_service.dart';
import '../services/firebase_auth_service.dart';

class AuthProvider with ChangeNotifier {
  final ApiService _apiService = ApiService();
  final FirebaseAuthService _firebaseAuthService = FirebaseAuthService();

  bool _isLoading = false;
  String? _errorMessage;
  String? _currentUser;
  String? _userFullName;
  String? _userEmail;
  String? _currentCompanyId;
  String _accountType = 'personal';

  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  String? get currentUser => _currentUser;
  String? get userFullName => _userFullName;
  String? get userEmail => _userEmail;
  String? get currentCompanyId => _currentCompanyId;
  bool get isAuthenticated => _currentUser != null;
  String get accountType => _accountType;
  bool get isPersonal => _accountType == 'personal';
  bool get isOrganization => _accountType == 'organization';

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

  Future<void> init() async {
    await _apiService.init();
    if (_apiService.isAuthenticated) {
      try {
        final response = await _apiService.get('/auth/me');
        final data = json.decode(response.body);
        _currentUser = data['public_id'] ?? data['id'] ?? 'user';
        _userFullName = data['full_name'];
        _userEmail = data['email'];
        _currentCompanyId = data['company_id'];
        _accountType = data['account_type'] ?? 'personal';
      } catch (_) {
        await _apiService.clearToken();
        _currentUser = null;
        _userFullName = null;
        _userEmail = null;
        _accountType = 'personal';
      }
      await _loadCompany();
      notifyListeners();
    }
  }

  Future<bool> login(String email, String password, {String accountType = 'personal', String? workspaceCode}) async {
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
      final token = data['access_token'];

      await _apiService.setToken(token);
      final meResponse = await _apiService.get('/auth/me');
      final me = json.decode(meResponse.body);
      _currentUser = me['public_id'] ?? me['id'] ?? 'user';
      _userFullName = me['full_name'];
      _userEmail = me['email'];
      _currentCompanyId = me['company_id'];
      _accountType = accountType; // Force to current login mode

      if (accountType == 'organization') {
        // If workspace login provided a workspace_id in the token response, use it
        if (data.containsKey('workspace_id')) {
           _currentCompanyId = data['workspace_id'];
        }
        _apiService.companyId = _currentCompanyId;
      } else {
        _currentCompanyId = null;
        _apiService.companyId = null;
      }

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
      final idToken = await _firebaseAuthService.signInWithGoogleAndGetIdToken();
      final response = await _apiService.post('/auth/firebase/google', body: {
        'id_token': idToken,
      });
      final data = json.decode(response.body);
      await _apiService.setToken(data['access_token']);

      final meResponse = await _apiService.get('/auth/me');
      final me = json.decode(meResponse.body);
      _currentUser = me['public_id'] ?? me['id'] ?? 'user';
      _userFullName = me['full_name'];
      _userEmail = me['email'];
      _currentCompanyId = null;
      _accountType = 'personal';
      _apiService.companyId = null;

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

      // Instead of calling /auth/login directly, use the updated login method
      // However, for a newly registered organization, we don't know the workspaceCode yet.
      // We will login using standard /auth/login for the first time just to get the token,
      // then load the company to set the companyId.
      final loginResponse = await _apiService.post('/auth/login', body: {
        'email': email,
        'password': password,
      });
      final data = json.decode(loginResponse.body);
      await _apiService.setToken(data['access_token']);
      
      final meResponse = await _apiService.get('/auth/me');
      final me = json.decode(meResponse.body);
      _currentUser = me['public_id'] ?? me['id'] ?? 'user';
      _userFullName = me['full_name'];
      _userEmail = me['email'];
      _accountType = accountType;

      if (accountType == 'organization') {
        await _loadCompany(); // sets _currentCompanyId and _apiService.companyId
      } else {
        _currentCompanyId = null;
        _apiService.companyId = null;
      }

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
    _currentUser = null;
    _userFullName = null;
    _userEmail = null;
    _currentCompanyId = null;
    _accountType = 'personal';
    notifyListeners();
  }

  String _friendlyGoogleError(Object error) {
    final message = error.toString();
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
