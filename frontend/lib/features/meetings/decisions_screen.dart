import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class Decision {
  final String id;
  final String title;
  final String? description;
  final String status;
  final String? type;
  final String? confidence;

  Decision({
    required this.id,
    required this.title,
    this.description,
    required this.status,
    this.type,
    this.confidence,
  });

  factory Decision.fromJson(Map<String, dynamic> json) {
    return Decision(
      id: json['id'] ?? '',
      title: json['title'] ?? 'Unknown Decision',
      description: json['description'],
      status: json['status'] ?? 'unknown',
      type: json['type'],
      confidence: json['confidence'],
    );
  }
}

class DecisionsScreen extends StatefulWidget {
  final String meetingId;
  final String? meetingTitle;

  const DecisionsScreen({
    super.key,
    required this.meetingId,
    this.meetingTitle,
  });

  @override
  State<DecisionsScreen> createState() => _DecisionsScreenState();
}

class _DecisionsScreenState extends State<DecisionsScreen> {
  List<Decision> decisions = [];
  bool isLoading = true;
  String? errorMessage;

  @override
  void initState() {
    super.initState();
    _loadDecisions();
  }

  Future<void> _loadDecisions() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      final response = await ApiService().get('/analysis/meetings/${widget.meetingId}/decisions');

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        final decisionsList = data['decisions'] as List;
        
        setState(() {
          decisions = decisionsList.map((d) => Decision.fromJson(d)).toList();
          isLoading = false;
        });
      } else {
        setState(() {
          errorMessage = 'Failed to load decisions';
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

  Color _getStatusColor(String status) {
    switch (status.toLowerCase()) {
      case 'agreed':
      case 'approved':
        return Colors.green;
      case 'rejected':
      case 'declined':
        return Colors.red;
      case 'proposed':
        return Colors.orange;
      default:
        return Colors.grey;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.meetingTitle ?? 'Meeting Decisions'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadDecisions,
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
              onPressed: _loadDecisions,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (decisions.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.gavel_outlined, size: 48, color: Colors.grey),
            const SizedBox(height: 16),
            const Text('No decisions available'),
            const SizedBox(height: 16),
            ElevatedButton(
              onPressed: _loadDecisions,
              child: const Text('Refresh'),
            ),
          ],
        ),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: decisions.length,
      itemBuilder: (context, index) {
        final decision = decisions[index];
        return Card(
          margin: const EdgeInsets.only(bottom: 12),
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.gavel, color: Colors.purple.shade700),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        decision.title,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: _getStatusColor(decision.status),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(
                        decision.status.toUpperCase(),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
                if (decision.description != null && decision.description!.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                    decision.description!,
                    style: TextStyle(
                      fontSize: 14,
                      color: Colors.grey.shade700,
                    ),
                  ),
                ],
                if (decision.type != null || decision.confidence != null) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      if (decision.type != null) ...[
                        Icon(Icons.label, size: 16, color: Colors.grey.shade600),
                        const SizedBox(width: 4),
                        Text(
                          decision.type!,
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.grey.shade600,
                          ),
                        ),
                      ],
                      if (decision.confidence != null) ...[
                        const SizedBox(width: 16),
                        Icon(Icons.bar_chart, size: 16, color: Colors.grey.shade600),
                        const SizedBox(width: 4),
                        Text(
                          decision.confidence!,
                          style: TextStyle(
                            fontSize: 12,
                            color: Colors.grey.shade600,
                          ),
                        ),
                      ],
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