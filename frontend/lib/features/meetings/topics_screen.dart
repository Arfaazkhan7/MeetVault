import 'package:flutter/material.dart';
import 'dart:convert';

import '../../core/services/api_service.dart';

class Topic {
  final String id;
  final String name;
  final String? description;
  final String? importance;

  Topic({
    required this.id,
    required this.name,
    this.description,
    this.importance,
  });

  factory Topic.fromJson(Map<String, dynamic> json) {
    return Topic(
      id: json['id'] ?? '',
      name: json['name'] ?? 'Unknown',
      description: json['description'],
      importance: json['importance'],
    );
  }
}

class TopicsScreen extends StatefulWidget {
  final String meetingId;
  final String? meetingTitle;

  const TopicsScreen({
    super.key,
    required this.meetingId,
    this.meetingTitle,
  });

  @override
  State<TopicsScreen> createState() => _TopicsScreenState();
}

class _TopicsScreenState extends State<TopicsScreen> {
  List<Topic> topics = [];
  bool isLoading = true;
  String? errorMessage;

  @override
  void initState() {
    super.initState();
    _loadTopics();
  }

  Future<void> _loadTopics() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      final response = await ApiService().get('/analysis/meetings/${widget.meetingId}/topics');

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final topicsList = data['topics'] as List;
        
        setState(() {
          topics = topicsList.map((t) => Topic.fromJson(t)).toList();
          isLoading = false;
        });
      } else {
        setState(() {
          errorMessage = 'Failed to load topics';
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

  Color _getImportanceColor(String? importance) {
    switch (importance?.toLowerCase()) {
      case 'high':
        return Colors.red;
      case 'medium':
        return Colors.orange;
      case 'low':
        return Colors.green;
      default:
        return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.meetingTitle ?? 'Meeting Topics'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadTopics,
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
              onPressed: _loadTopics,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (topics.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.topic_outlined, size: 48, color: Colors.grey),
            const SizedBox(height: 16),
            const Text('No topics available'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadTopics,
              child: const Text('Refresh'),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: topics.length,
      itemBuilder: (context, index) {
        final topic = topics[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.topic, color: Colors.blue.shade700),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        topic.name,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    if (topic.importance != null)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 4,
                        ),
                        decoration: BoxDecoration(
                          color: _getImportanceColor(topic.importance),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Text(
                          topic.importance!.toUpperCase(),
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                  ],
                ),
                if (topic.description != null && topic.description!.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                    topic.description!,
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.grey.shade700,
                    ),
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
