import 'dart:convert';

import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/services/api_service.dart';
import '../../core/widgets/enterprise_scaffold.dart';

class ProjectsScreen extends StatefulWidget {
  const ProjectsScreen({super.key});

  @override
  State<ProjectsScreen> createState() => _ProjectsScreenState();
}

class _ProjectsScreenState extends State<ProjectsScreen> {
  final _api = ApiService();
  final _search = TextEditingController();
  List<Map<String, dynamic>> _projects = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
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
          _projects = [];
          _loading = false;
        });
        return;
      }
      final projectsResponse = await _api.get('/companies/${companies.first['public_id']}/projects');
      final projects = (json.decode(projectsResponse.body) as List).whereType<Map>().toList();
      setState(() {
        _projects = projects.map((item) => Map<String, dynamic>.from(item)).toList();
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
      title: 'Projects',
      currentRoute: AppRouter.projects,
      actions: [IconButton(tooltip: 'Refresh', onPressed: _load, icon: const Icon(Icons.refresh))],
      child: _body(),
    );
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return UiState.error(_error!, onRetry: _load);
    final query = _search.text.toLowerCase();
    final visible = query.isEmpty ? _projects : _projects.where((item) => json.encode(item).toLowerCase().contains(query)).toList();
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        TextField(
          controller: _search,
          decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search projects'),
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: 16),
        if (visible.isEmpty)
          const SizedBox(height: 320, child: UiState.empty('No projects are available for your companies.'))
        else
          for (final item in visible)
            Card(
              child: ListTile(
                leading: const CircleAvatar(child: Icon(Icons.folder_outlined)),
                title: Text('${item['name'] ?? 'Untitled project'}'),
                subtitle: Text('${item['public_id'] ?? ''}  ${item['status'] ?? ''}'),
                trailing: IconButton(
                  tooltip: 'Open dashboard',
                  onPressed: () => Navigator.pushNamed(context, AppRouter.projectDashboard, arguments: {'id': item['public_id']}),
                  icon: const Icon(Icons.chevron_right),
                ),
              ),
            ),
      ],
    );
  }
}
