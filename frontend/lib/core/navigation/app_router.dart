import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../../features/auth/login_screen.dart';
import '../../features/auth/register_screen.dart';
import '../../features/dashboard/dashboard_screen.dart';
import '../../features/companies/company_screen.dart';
import '../../features/users/users_screen.dart';
import '../../features/projects/projects_screen.dart';
import '../../features/projects/project_dashboard_screen.dart';
import '../../features/meetings/meetings_screen.dart';
import '../../features/meetings/meeting_details_screen.dart';
import '../../features/meetings/meeting_room_screen.dart';
import '../../features/meetings/join_meeting_screen.dart';
import '../../features/meetings/participants_screen.dart';
import '../../features/meetings/transcript_screen.dart';
import '../../features/meetings/meeting_summary_screen.dart';
import '../../features/meetings/topics_screen.dart';
import '../../features/meetings/decisions_screen.dart';
import '../../features/meetings/tasks_screen.dart';
import '../../features/documents/documents_screen.dart';
import '../../features/memory/project_memory_screen.dart';
import '../../features/memory/topic_evolution_screen.dart';
import '../../features/memory/decision_history_screen.dart';
import '../../features/search/search_screen.dart';
import '../../features/memory/ask_memory_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../features/admin/admin_login_screen.dart';
import '../../features/admin/admin_screen.dart';

class AppRouter {
  static const String login = '/login';
  static const String register = '/register';
  static const String dashboard = '/dashboard';
  static const String companies = '/companies';
  static const String users = '/users';
  static const String projects = '/projects';
  static const String projectDashboard = '/projects/:id';
  static const String meetings = '/meetings';
  static const String meetingDetails = '/meetings/:id';
  static const String meetingRoom = '/meetings/:id/room';
  static const String joinMeeting = '/join';
  static const String participants = '/meetings/:id/participants';
  static const String transcript = '/meetings/:id/transcript';
  static const String summary = '/meetings/:id/summary';
  static const String topics = '/meetings/:id/topics';
  static const String decisions = '/meetings/:id/decisions';
  static const String tasks = '/meetings/:id/tasks';
  static const String documents = '/documents';
  static const String projectMemory = '/memory';
  static const String topicEvolution = '/memory/topics';
  static const String decisionHistory = '/memory/decisions';
  static const String search = '/search';
  static const String askMemory = '/ask';
  static const String settings = '/settings';
  static const String admin = '/admin';
  static const String adminLogin = '/admin/login';
  static const String adminDashboard = '/admin/dashboard';

  static Map<String, WidgetBuilder> get routes => {
    login: (context) => const LoginScreen(),
    register: (context) => const RegisterScreen(),
    dashboard: (context) => const DashboardScreen(),
    companies: (context) => const CompanyScreen(),
    users: (context) => const UsersScreen(),
    projects: (context) => const ProjectsScreen(),
    meetings: (context) => const MeetingsScreen(),
    documents: (context) => const DocumentsScreen(),
    projectMemory: (context) => const ProjectMemoryScreen(),
    topicEvolution: (context) => const TopicEvolutionScreen(),
    decisionHistory: (context) => const DecisionHistoryScreen(),
    search: (context) => const SearchScreen(),
    askMemory: (context) => const AskMemoryScreen(),
    settings: (context) => const SettingsScreen(),
    admin: (context) => const AdminDashboardScreen(),
    adminLogin: (context) => const AdminLoginScreen(),
    adminDashboard: (context) => const AdminDashboardScreen(),
    joinMeeting: (context) => const JoinMeetingScreen(),
  };

  static Route<dynamic> onGenerateRoute(RouteSettings settings) {
    switch (settings.name) {
      case projectDashboard:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => ProjectDashboardScreen(projectId: args['id']),
        );
      case meetingDetails:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => MeetingDetailsScreen(meetingId: args['id']),
        );
      case meetingRoom:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => MeetingRoomScreen(
            meetingId: args['id'],
            meetingTitle: args['title'] ?? 'Meeting Room',
            authToken: ApiService().token ?? '',
            livekitUrl: args['livekitUrl'],
            token: args['token'],
            roomName: args['roomName'],
            isHost: args['isHost'] ?? false,
          ),
        );
      case joinMeeting:
        final args = settings.arguments as Map<String, dynamic>?;
        
        // Handle URL-based join route /join/:code (from settings.name)
        String? code = args?['code'] as String?;
        if (code == null && settings.name != null && settings.name!.startsWith('/join/')) {
          final parts = settings.name!.split('/');
          if (parts.length > 2) {
            code = Uri.decodeComponent(parts[2]);
          }
        }
        
        return MaterialPageRoute(
          builder: (context) => JoinMeetingScreen(initialCode: code),
        );
      case participants:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => ParticipantsScreen(meetingId: args['id']),
        );
      case transcript:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => TranscriptScreen(meetingId: args['id']),
        );
      case summary:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => MeetingSummaryScreen(meetingId: args['id']),
        );
      case topics:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => TopicsScreen(meetingId: args['id']),
        );
      case decisions:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => DecisionsScreen(meetingId: args['id']),
        );
      case tasks:
        final args = settings.arguments as Map<String, dynamic>;
        return MaterialPageRoute(
          builder: (context) => TasksScreen(meetingId: args['id']),
        );
      default:
        // Handle URL-based join route matching /join/:code that fallback here
        if (settings.name != null && settings.name!.startsWith('/join/')) {
          final parts = settings.name!.split('/');
          if (parts.length > 2) {
            return MaterialPageRoute(
              builder: (context) => JoinMeetingScreen(initialCode: Uri.decodeComponent(parts[2])),
            );
          }
        }
        return MaterialPageRoute(
          builder: (context) => const DashboardScreen(),
        );
    }
  }
}
