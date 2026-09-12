import 'package:flutter/material.dart';
import 'dart:convert';

import '../../core/services/api_service.dart';

class Evidence {
  final String id;
  final String evidenceType;
  final String content;
  final String? context;
  final double? timestamp;
  final String? speakerLabel;
  final String? userId;
  final double? confidence;
  final String? topicId;
  final String? decisionId;
  final String? taskId;

  Evidence({
    required this.id,
    required this.evidenceType,
    required this.content,
    this.context,
    this.timestamp,
    this.speakerLabel,
    this.userId,
    this.confidence,
    this.topicId,
    this.decisionId,
    this.taskId,
  });

  factory Evidence.fromJson(Map<String, dynamic> json) {
    return Evidence(
      id: json['id'] ?? '',
      evidenceType: json['evidence_type'] ?? 'unknown',
      content: json['content'] ?? '',
      context: json['context'],
      timestamp: json['timestamp']?.toDouble(),
      speakerLabel: json['speaker_label'],
      userId: json['user_id'],
      confidence: json['confidence']?.toDouble(),
      topicId: json['topic_id'],
      decisionId: json['decision_id'],
      taskId: json['task_id'],
    );
  }
}

class EvidenceScreen extends StatefulWidget {
  final String meetingId;
  final String? meetingTitle;

  const EvidenceScreen({
    super.key,
    required this.meetingId,
    this.meetingTitle,
  });

  @override
  State<EvidenceScreen> createState() => _EvidenceScreenState();
}

class _EvidenceScreenState extends State<EvidenceScreen> {
  List<Evidence> evidence = [];
  bool isLoading = true;
  String? errorMessage;
  String? selectedType;

  @override
  void initState() {
    super.initState();
    _loadEvidence();
  }

  Future<void> _loadEvidence() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      String endpoint = '/analysis/meetings/${widget.meetingId}/evidence';
      if (selectedType != null) {
        endpoint += '?evidence_type=$selectedType';
      }

      final response = await ApiService().get(endpoint);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final evidenceList = data['evidence'] as List;
        
        setState(() {
          evidence = evidenceList.map((e) => Evidence.fromJson(e)).toList();
          isLoading = false;
        });
      } else {
        setState(() {
          errorMessage = 'Failed to load evidence';
          isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        errorMessage = 'Error: $e';
        isLoading = false;
      });
    }
  }

  List<String> _getAvailableTypes() {
    final types = evidence.map((e) => e.evidenceType).toSet().toList();
    types.sort();
    return types;
  }

  Color _getTypeColor(String type) {
    switch (type.toLowerCase()) {
      case 'summary':
        return Colors.blue;
      case 'topic':
        return Colors.purple;
      case 'decision':
        return Colors.orange;
      case 'task':
        return Colors.green;
      case 'agreement':
        return Colors.teal;
      case 'disagreement':
        return Colors.red;
      default:
        return Colors.grey;
    }
  }

  String _formatTimestamp(double? timestamp) {
    if (timestamp == null) return 'N/A';
    final minutes = (timestamp / 60).floor();
    final seconds = (timestamp % 60).floor();
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.meetingTitle ?? 'Meeting Evidence'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadEvidence,
          ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.filter_list),
            onSelected: (type) {
              setState(() {
                selectedType = type == 'all' ? null : type;
              });
              _loadEvidence();
            },
            itemBuilder: (context) {
              return [
                const PopupMenuItem(value: 'all', child: Text('All Types')),
                ..._getAvailableTypes().map((type) {
                  return PopupMenuItem(value: type, child: Text(type));
                }),
              ];
            },
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (isLoading) {
      return const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (errorMessage != null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.error_outline, size: 48, color: Colors.red),
            const SizedBox(height: 16),
            Text(
              errorMessage!,
              style: const TextStyle(color: Colors.red),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadEvidence,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (evidence.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.find_in_page_outlined, size: 48, color: Colors.grey),
            const SizedBox(height: 16),
            const Text('No evidence available'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadEvidence,
              child: const Text('Refresh'),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: evidence.length,
      itemBuilder: (context, index) {
        final ev = evidence[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: _getTypeColor(ev.evidenceType),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        ev.evidenceType.toUpperCase(),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    if (ev.timestamp != null)
                      Text(
                        _formatTimestamp(ev.timestamp),
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey.shade600,
                        ),
                      ),
                    const Spacer(),
                    if (ev.confidence != null)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: ev.confidence! >= 0.8
                              ? Colors.green
                              : ev.confidence! >= 0.6
                                  ? Colors.orange
                                  : Colors.red,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          '${(ev.confidence! * 100).toStringAsFixed(0)}%',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 8),
                if (ev.speakerLabel != null)
                  Row(
                    children: [
                      Icon(Icons.person, size: 16, color: Colors.grey.shade600),
                      const SizedBox(width: 4),
                      Text(
                        ev.speakerLabel!,
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.grey.shade600,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: 8),
                Text(
                  ev.content,
                  style: const TextStyle(fontSize: 14),
                ),
                if (ev.context != null && ev.context!.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade100,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      ev.context!,
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey.shade700,
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ),
                ],
                if (ev.topicId != null || ev.decisionId != null || ev.taskId != null) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    children: [
                      if (ev.topicId != null)
                        Chip(
                          label: const Text('Topic'),
                          avatar: const Icon(Icons.topic, size: 16),
                          backgroundColor: Colors.purple.shade100,
                        ),
                      if (ev.decisionId != null)
                        Chip(
                          label: const Text('Decision'),
                          avatar: const Icon(Icons.gavel, size: 16),
                          backgroundColor: Colors.orange.shade100,
                        ),
                      if (ev.taskId != null)
                        Chip(
                          label: const Text('Task'),
                          avatar: const Icon(Icons.task, size: 16),
                          backgroundColor: Colors.green.shade100,
                        ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
