import 'package:flutter/material.dart';
import '../providers/auth_provider.dart';
import '../services/api_service.dart';
import '../widgets/auth_splash_gate.dart';
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

  static Route<dynamic> onGenerateRoute(RouteSettings settings, AuthProvider authProvider) {
    // 1. While auth status is initializing (/auth/me in progress), show splash gate (zero dashboard flash)
    if (authProvider.isInitializing) {
      return MaterialPageRoute(
        builder: (context) => const AuthSplashGate(),
        settings: settings,
      );
    }

    final routeName = settings.name ?? '/';

    // Extract deep-link meeting code if present (e.g. /join/MTG-ABC123)
    String? joinCode;
    if (routeName == joinMeeting || routeName.startsWith('/join/')) {
      final parts = routeName.split('/');
      if (parts.length > 2 && parts[2].trim().isNotEmpty) {
        joinCode = Uri.decodeComponent(parts[2].trim());
      } else if (settings.arguments is Map<String, dynamic>) {
        final args = settings.arguments as Map<String, dynamic>;
        joinCode = args['code'] as String?;
      }
    }

    // 2. UNAUTHENTICATED GUARD
    if (!authProvider.isAuthenticated) {
      // Store deep-link invite code if visiting /join/<code> unauthenticated
      if (joinCode != null && joinCode.isNotEmpty) {
        authProvider.pendingInviteCode = joinCode;
      }

      // Public unauthenticated routes
      if (routeName == login) {
        return MaterialPageRoute(
          builder: (context) => const LoginScreen(),
          settings: const RouteSettings(name: login),
        );
      }
      if (routeName == register) {
        return MaterialPageRoute(
          builder: (context) => const RegisterScreen(),
          settings: const RouteSettings(name: register),
        );
      }
      if (routeName == adminLogin) {
        return MaterialPageRoute(
          builder: (context) => const AdminLoginScreen(),
          settings: const RouteSettings(name: adminLogin),
        );
      }

      // Any protected route or unknown route visited while unauthenticated -> Redirect to Login
      return MaterialPageRoute(
        builder: (context) => const LoginScreen(),
        settings: const RouteSettings(name: login),
      );
    }

    // 3. AUTHENTICATED GUARD
    // If authenticated user visits /login or /register, redirect to dashboard (or pending invite route)
    if (routeName == login || routeName == register) {
      final pendingCode = authProvider.pendingInviteCode;
      if (pendingCode != null && pendingCode.isNotEmpty) {
        authProvider.clearPendingInviteCode();
        return MaterialPageRoute(
          builder: (context) => JoinMeetingScreen(initialCode: pendingCode),
          settings: RouteSettings(name: '/join/$pendingCode'),
        );
      }
      return MaterialPageRoute(
        builder: (context) => const DashboardScreen(),
        settings: const RouteSettings(name: dashboard),
      );
    }

    // Handle /join route for authenticated user
    if (routeName == joinMeeting || routeName.startsWith('/join/')) {
      final codeToUse = joinCode ?? authProvider.pendingInviteCode;
      if (authProvider.pendingInviteCode != null) {
        authProvider.clearPendingInviteCode();
      }
      return MaterialPageRoute(
        builder: (context) => JoinMeetingScreen(initialCode: codeToUse),
        settings: settings,
      );
    }

    // Match static authenticated routes
    switch (routeName) {
      case dashboard:
      case '/':
        return MaterialPageRoute(
          builder: (context) => const DashboardScreen(),
          settings: const RouteSettings(name: dashboard),
        );
      case companies:
        return MaterialPageRoute(
          builder: (context) => const CompanyScreen(),
          settings: settings,
        );
      case users:
        return MaterialPageRoute(
          builder: (context) => const UsersScreen(),
          settings: settings,
        );
      case projects:
        return MaterialPageRoute(
          builder: (context) => const ProjectsScreen(),
          settings: settings,
        );
      case meetings:
        return MaterialPageRoute(
          builder: (context) => const MeetingsScreen(),
          settings: settings,
        );
      case documents:
        return MaterialPageRoute(
          builder: (context) => const DocumentsScreen(),
          settings: settings,
        );
      case projectMemory:
        return MaterialPageRoute(
          builder: (context) => const ProjectMemoryScreen(),
          settings: settings,
        );
      case topicEvolution:
        return MaterialPageRoute(
          builder: (context) => const TopicEvolutionScreen(),
          settings: settings,
        );
      case decisionHistory:
        return MaterialPageRoute(
          builder: (context) => const DecisionHistoryScreen(),
          settings: settings,
        );
      case search:
        return MaterialPageRoute(
          builder: (context) => const SearchScreen(),
          settings: settings,
        );
      case askMemory:
        return MaterialPageRoute(
          builder: (context) => const AskMemoryScreen(),
          settings: settings,
        );
      case settings:
        return MaterialPageRoute(
          builder: (context) => const SettingsScreen(),
          settings: settings,
        );
      case admin:
      case adminDashboard:
        return MaterialPageRoute(
          builder: (context) => const AdminDashboardScreen(),
          settings: settings,
        );
      case adminLogin:
        return MaterialPageRoute(
          builder: (context) => const AdminDashboardScreen(),
          settings: const RouteSettings(name: adminDashboard),
        );
    }

    // Parameterized route matching for authenticated users
    if (routeName.startsWith('/projects/')) {
      final parts = routeName.split('/');
      if (parts.length > 2 && parts[2].trim().isNotEmpty) {
        final projectId = Uri.decodeComponent(parts[2]);
        return MaterialPageRoute(
          builder: (context) => ProjectDashboardScreen(projectId: projectId),
          settings: settings,
        );
      }
    }

    if (routeName.startsWith('/meetings/')) {
      final parts = routeName.split('/');
      if (parts.length > 2 && parts[2].trim().isNotEmpty) {
        final meetingId = Uri.decodeComponent(parts[2]);
        if (parts.length > 3) {
          final sub = parts[3];
          if (sub == 'room') {
            final args = (settings.arguments as Map<String, dynamic>?) ?? {};
            return MaterialPageRoute(
              builder: (context) => MeetingRoomScreen(
                meetingId: meetingId,
                meetingTitle: args['title'] ?? 'Meeting Room',
                authToken: ApiService().token ?? '',
                livekitUrl: args['livekitUrl'],
                token: args['token'],
                roomName: args['roomName'],
                isHost: args['isHost'] ?? false,
              ),
              settings: settings,
            );
          } else if (sub == 'participants') {
            return MaterialPageRoute(
              builder: (context) => ParticipantsScreen(meetingId: meetingId),
              settings: settings,
            );
          } else if (sub == 'transcript') {
            return MaterialPageRoute(
              builder: (context) => TranscriptScreen(meetingId: meetingId),
              settings: settings,
            );
          } else if (sub == 'summary') {
            return MaterialPageRoute(
              builder: (context) => MeetingSummaryScreen(meetingId: meetingId),
              settings: settings,
            );
          } else if (sub == 'topics') {
            return MaterialPageRoute(
              builder: (context) => TopicsScreen(meetingId: meetingId),
              settings: settings,
            );
          } else if (sub == 'decisions') {
            return MaterialPageRoute(
              builder: (context) => DecisionsScreen(meetingId: meetingId),
              settings: settings,
            );
          } else if (sub == 'tasks') {
            return MaterialPageRoute(
              builder: (context) => TasksScreen(meetingId: meetingId),
              settings: settings,
            );
          }
        }
        return MaterialPageRoute(
          builder: (context) => MeetingDetailsScreen(meetingId: meetingId),
          settings: settings,
        );
      }
    }

    // Handle parameterized routes passed via arguments
    if (settings.arguments is Map<String, dynamic>) {
      final args = settings.arguments as Map<String, dynamic>;
      if (routeName == projectDashboard && args.containsKey('id')) {
        return MaterialPageRoute(
          builder: (context) => ProjectDashboardScreen(projectId: args['id']),
          settings: settings,
        );
      }
      if (routeName == meetingDetails && args.containsKey('id')) {
        return MaterialPageRoute(
          builder: (context) => MeetingDetailsScreen(meetingId: args['id']),
          settings: settings,
        );
      }
    }

    // Unknown route fallback when authenticated: DashboardScreen
    return MaterialPageRoute(
      builder: (context) => const DashboardScreen(),
      settings: const RouteSettings(name: dashboard),
    );
  }
}
