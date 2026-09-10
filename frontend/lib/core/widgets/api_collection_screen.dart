import 'dart:convert';

import 'package:flutter/material.dart';
import '../services/api_service.dart';
import 'enterprise_scaffold.dart';

class ApiCollectionScreen extends StatefulWidget {
  final String title;
  final String route;
  final IconData icon;
  final String endpoint;
  final String emptyMessage;
  final String Function(Map<String, dynamic>) itemTitle;
  final String Function(Map<String, dynamic>)? itemSubtitle;
  final String? collectionKey;
  final List<Widget> Function(BuildContext, Map<String, dynamic>)? itemActions;

  const ApiCollectionScreen({
    super.key,
    required this.title,
    required this.route,
    required this.icon,
    required this.endpoint,
    required this.emptyMessage,
    required this.itemTitle,
    this.itemSubtitle,
    this.collectionKey,
    this.itemActions,
  });

  @override
  State<ApiCollectionScreen> createState() => _ApiCollectionScreenState();
}

class _ApiCollectionScreenState extends State<ApiCollectionScreen> {
  final _api = ApiService();
  final _search = TextEditingController();
  List<Map<String, dynamic>> _items = [];
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
      final response = await _api.get(widget.endpoint);
      final decoded = json.decode(response.body);
      final raw = widget.collectionKey == null ? decoded : decoded[widget.collectionKey];
      final list = raw is List ? raw : <dynamic>[];
      setState(() {
        _items = list.whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
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
      title: widget.title,
      currentRoute: widget.route,
      actions: [IconButton(tooltip: 'Refresh', onPressed: _load, icon: const Icon(Icons.refresh))],
      child: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return UiState.error(_error!, onRetry: _load);
    final query = _search.text.trim().toLowerCase();
    final filtered = query.isEmpty
        ? _items
        : _items.where((item) => json.encode(item).toLowerCase().contains(query)).toList();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _search,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search),
              hintText: 'Search ${widget.title.toLowerCase()}',
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Clear',
                      onPressed: () => setState(_search.clear),
                      icon: const Icon(Icons.close),
                    ),
            ),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: 16),
          if (filtered.isEmpty)
            SizedBox(height: 360, child: UiState.empty(widget.emptyMessage))
          else
            for (final item in filtered)
              Card(
                margin: const EdgeInsets.only(bottom: 10),
                child: ListTile(
                  leading: CircleAvatar(child: Icon(widget.icon)),
                  title: Text(widget.itemTitle(item), maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: widget.itemSubtitle == null
                      ? null
                      : Text(widget.itemSubtitle!(item), maxLines: 2, overflow: TextOverflow.ellipsis),
                  trailing: widget.itemActions == null
                      ? null
                      : Wrap(spacing: 4, children: widget.itemActions!(context, item)),
                ),
              ),
        ],
      ),
    );
  }
}
