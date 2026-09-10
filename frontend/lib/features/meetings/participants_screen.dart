import 'package:flutter/material.dart';
import '../../core/navigation/app_router.dart';
import '../../core/widgets/api_collection_screen.dart';

class ParticipantsScreen extends StatelessWidget {
  final String meetingId;

  const ParticipantsScreen({super.key, required this.meetingId});

  @override
  Widget build(BuildContext context) {
    return ApiCollectionScreen(
      title: 'Participants',
      route: AppRouter.meetings,
      icon: Icons.person_outline,
      endpoint: '/meetings/$meetingId/participants',
      emptyMessage: 'No participants are assigned to this meeting.',
      itemTitle: (item) => '${item['full_name'] ?? item['email'] ?? item['user_public_id']}',
      itemSubtitle: (item) => '${item['role'] ?? ''}  ${item['status'] ?? ''}',
    );
  }
}
