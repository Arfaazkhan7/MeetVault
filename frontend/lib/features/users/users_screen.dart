import 'dart:convert';

import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class UsersScreen extends StatefulWidget {
  const UsersScreen({super.key});

  @override
  State<UsersScreen> createState() => _UsersScreenState();
}

class _UsersScreenState extends State<UsersScreen> {
  final _api = ApiService();
  List<Map<String, dynamic>> _members = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final companiesResponse = await _api.get('/companies');
      final companies = (json.decode(companiesResponse.body) as List).whereType<Map>().toList();
      if (companies.isEmpty) {
        setState(() {
          _members = [];
          _loading = false;
        });
        return;
      }
      final response = await _api.get('/companies/${companies.first['public_id']}/members');
      final members = (json.decode(response.body) as List).whereType<Map>().toList();
      setState(() {
        _members = members.map((item) => Map<String, dynamic>.from(item)).toList();
        _loading = false;
      });
    } catch (error) {
      setState(() {
        _error = error.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return EnterpriseScaffold(
      title: 'Users',
      currentRoute: AppRouter.users,
      actions: [IconButton(tooltip: 'Refresh', onPressed: _load, icon: const Icon(Icons.refresh))],
      child: _body(),
    );
  }

  void _showMemberDetail(Map<String, dynamic> member) {
    final name = member['full_name'] ?? member['email'] ?? 'User';
    final email = member['email'] ?? 'No email provided';
    final role = member['role'] ?? 'Member';
    final userId = member['user_id'] ?? member['public_id'] ?? 'USR-0001';

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        contentPadding: const EdgeInsets.all(24),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: const Color(0xFFFF5722),
              child: Text(
                name[0].toUpperCase(),
                style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(height: 14),
            Text(name, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0F172A))),
            Text(email, style: const TextStyle(fontSize: 12, color: Color(0xFF64748B))),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFFF8FAFC),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFE2E8F0)),
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('User ID', style: TextStyle(fontSize: 12, color: Color(0xFF64748B))),
                      Text(userId, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const Divider(height: 14),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Role', style: TextStyle(fontSize: 12, color: Color(0xFF64748B))),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(color: const Color(0xFFFFF1EB), borderRadius: BorderRadius.circular(6)),
                        child: Text(role, style: const TextStyle(fontSize: 11, color: Color(0xFFFF5722), fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                  const Divider(height: 14),
                  const Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Status', style: TextStyle(fontSize: 12, color: Color(0xFF64748B))),
                      Text('Active Member', style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Color(0xFF10B981))),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                style: FilledButton.styleFrom(backgroundColor: const Color(0xFF1E293B)),
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Close'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return UiState.error(_error!, onRetry: _load);
    if (_members.isEmpty) return const UiState.empty('No company members are available.');
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        for (final member in _members)
          Card(
            margin: const EdgeInsets.only(bottom: 10),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            child: ListTile(
              onTap: () => _showMemberDetail(member),
              leading: CircleAvatar(
                backgroundColor: const Color(0xFFFFF1EB),
                child: Text(
                  (member['full_name'] ?? member['email'] ?? 'U')[0].toUpperCase(),
                  style: const TextStyle(color: Color(0xFFFF5722), fontWeight: FontWeight.bold),
                ),
              ),
              title: Text(
                '${member['full_name'] ?? member['email'] ?? 'User'}',
                style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14),
              ),
              subtitle: Text('${member['email'] ?? ''} • ${member['role'] ?? 'Member'}'),
              trailing: const Icon(Icons.chevron_right, color: Color(0xFF64748B)),
            ),
          ),
      ],
    );
  }
}
