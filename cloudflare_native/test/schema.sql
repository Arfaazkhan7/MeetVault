-- Test schema compiled from existing SQLAlchemy models; embeddings use text in tests.

CREATE TABLE ai_jobs (
	public_id VARCHAR NOT NULL, 
	meeting_id VARCHAR NOT NULL, 
	recording_id VARCHAR NOT NULL, 
	company_id VARCHAR, 
	requested_by_user_id VARCHAR NOT NULL, 
	job_type VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	current_stage VARCHAR NOT NULL, 
	retry_count INTEGER NOT NULL, 
	max_retries INTEGER NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	failed_at TIMESTAMP WITH TIME ZONE, 
	error_message TEXT, 
	provider VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ai_job_recording_type UNIQUE (recording_id, job_type)
)

;

CREATE TABLE commitments (
	meeting_id VARCHAR NOT NULL, 
	project_id VARCHAR, 
	person VARCHAR NOT NULL, 
	participant_id VARCHAR, 
	commitment TEXT NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR NOT NULL, 
	source_segment_id VARCHAR, 
	source_start_ms FLOAT, 
	source_end_ms FLOAT, 
	confidence VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE companies (
	public_id VARCHAR NOT NULL, 
	workspace_code VARCHAR, 
	name VARCHAR NOT NULL, 
	domain VARCHAR, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE company_members (
	user_id VARCHAR NOT NULL, 
	company_id VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	department VARCHAR, 
	job_title VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_member_company UNIQUE (user_id, company_id)
)

;

CREATE TABLE decision_history (
	public_id VARCHAR, 
	decision_id VARCHAR NOT NULL, 
	meeting_id VARCHAR NOT NULL, 
	stage VARCHAR NOT NULL, 
	previous_status VARCHAR, 
	new_status VARCHAR NOT NULL, 
	notes TEXT, 
	evidence_text TEXT, 
	reason TEXT, 
	speaker_label VARCHAR, 
	changed_by VARCHAR, 
	timestamp TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE decisions (
	company_id VARCHAR NOT NULL, 
	meeting_id VARCHAR NOT NULL, 
	project_id VARCHAR, 
	title VARCHAR NOT NULL, 
	description TEXT, 
	status VARCHAR NOT NULL, 
	decision_type VARCHAR, 
	proposer_id VARCHAR, 
	confidence_level VARCHAR, 
	original_proposal TEXT, 
	reason TEXT, 
	source_segment_id VARCHAR, 
	source_start_ms FLOAT, 
	source_end_ms FLOAT, 
	speaker_label VARCHAR, 
	extracted_by VARCHAR, 
	extraction_confidence VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE document_pages (
	public_id VARCHAR NOT NULL, 
	document_id VARCHAR NOT NULL, 
	page_number INTEGER NOT NULL, 
	text_content VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE documents (
	public_id VARCHAR NOT NULL, 
	company_id VARCHAR NOT NULL, 
	project_id VARCHAR, 
	meeting_id VARCHAR, 
	uploader_id VARCHAR, 
	title VARCHAR NOT NULL, 
	file_name VARCHAR NOT NULL, 
	file_type VARCHAR NOT NULL, 
	file_size INTEGER, 
	file_url VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	page_count INTEGER NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE embeddings (
	public_id VARCHAR, 
	company_id VARCHAR NOT NULL, 
	project_id VARCHAR, 
	meeting_id VARCHAR, 
	source_type VARCHAR NOT NULL, 
	source_id VARCHAR NOT NULL, 
	content_text TEXT, 
	speaker_label VARCHAR, 
	participant_id VARCHAR, 
	embedding TEXT, 
	vector_data TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE evidence (
	meeting_id VARCHAR NOT NULL, 
	transcript_segment_id VARCHAR, 
	timestamp FLOAT, 
	speaker_label VARCHAR, 
	user_id VARCHAR, 
	content TEXT NOT NULL, 
	context TEXT, 
	evidence_type VARCHAR NOT NULL, 
	confidence FLOAT, 
	topic_id VARCHAR, 
	decision_id VARCHAR, 
	task_id VARCHAR, 
	question_id VARCHAR, 
	risk_id VARCHAR, 
	commitment_id VARCHAR, 
	unresolved_issue_id VARCHAR, 
	extracted_by VARCHAR, 
	extraction_metadata TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE meeting_participants (
	user_id VARCHAR, 
	meeting_id VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	join_time TIMESTAMP WITH TIME ZONE, 
	leave_time TIMESTAMP WITH TIME ZONE, 
	attendance_duration_seconds INTEGER, 
	livekit_identity VARCHAR, 
	identity_mapping_status VARCHAR NOT NULL, 
	is_guest BOOLEAN NOT NULL, 
	display_name VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_participant_meeting UNIQUE (user_id, meeting_id)
)

;

CREATE TABLE meeting_recordings (
	meeting_id VARCHAR NOT NULL, 
	company_id VARCHAR, 
	uploaded_by_user_id VARCHAR NOT NULL, 
	session_id VARCHAR, 
	egress_id VARCHAR, 
	source VARCHAR, 
	storage_backend VARCHAR NOT NULL, 
	storage_bucket VARCHAR, 
	storage_path VARCHAR, 
	original_filename VARCHAR, 
	file_type VARCHAR, 
	file_size_bytes BIGINT, 
	duration_seconds INTEGER, 
	processing_status VARCHAR NOT NULL, 
	processing_error TEXT, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	is_audio_purged BOOLEAN NOT NULL, 
	audio_purged_at TIMESTAMP WITH TIME ZONE, 
	retention_policy VARCHAR, 
	cleanup_error TEXT, 
	cleanup_retry_count INTEGER NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE meeting_summaries (
	meeting_id VARCHAR NOT NULL, 
	company_id VARCHAR NOT NULL, 
	summary_text TEXT NOT NULL, 
	key_takeaways TEXT, 
	questions TEXT, 
	answers TEXT, 
	suggestions TEXT, 
	proposals TEXT, 
	concerns TEXT, 
	agreements TEXT, 
	disagreements TEXT, 
	extracted_by VARCHAR, 
	extraction_confidence VARCHAR, 
	extraction_metadata TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE meeting_topics (
	company_id VARCHAR NOT NULL, 
	meeting_id VARCHAR NOT NULL, 
	topic_id VARCHAR NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_meeting_topic UNIQUE (meeting_id, topic_id)
)

;

CREATE TABLE meetings (
	public_id VARCHAR NOT NULL, 
	company_id VARCHAR, 
	project_id VARCHAR, 
	owner_id VARCHAR, 
	title VARCHAR NOT NULL, 
	description VARCHAR, 
	meeting_type VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	scheduled_start_time TIMESTAMP WITH TIME ZONE, 
	start_time TIMESTAMP WITH TIME ZONE, 
	end_time TIMESTAMP WITH TIME ZONE, 
	duration_seconds INTEGER, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	invite_code VARCHAR, 
	transcription_status VARCHAR NOT NULL, 
	transcription_error TEXT, 
	recording_url VARCHAR, 
	analysis_status VARCHAR NOT NULL, 
	analysis_error TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE project_members (
	user_id VARCHAR NOT NULL, 
	project_id VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_member_project UNIQUE (user_id, project_id)
)

;

CREATE TABLE projects (
	public_id VARCHAR NOT NULL, 
	company_id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	description VARCHAR, 
	status VARCHAR NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE questions (
	meeting_id VARCHAR NOT NULL, 
	project_id VARCHAR, 
	question TEXT NOT NULL, 
	asked_by_participant_id VARCHAR, 
	mentioned_to_participant_id VARCHAR, 
	status VARCHAR NOT NULL, 
	answer TEXT, 
	answered_by_participant_id VARCHAR, 
	source_segment_id VARCHAR, 
	source_start_ms FLOAT, 
	source_end_ms FLOAT, 
	confidence VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE reminders (
	user_id VARCHAR NOT NULL, 
	action_item_id VARCHAR, 
	commitment_id VARCHAR, 
	remind_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR NOT NULL, 
	sent_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE risks (
	meeting_id VARCHAR NOT NULL, 
	project_id VARCHAR, 
	title VARCHAR NOT NULL, 
	description TEXT, 
	severity VARCHAR, 
	probability VARCHAR, 
	owner_participant_id VARCHAR, 
	status VARCHAR NOT NULL, 
	source_segment_id VARCHAR, 
	source_start_ms FLOAT, 
	source_end_ms FLOAT, 
	confidence VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE speaker_mappings (
	meeting_id VARCHAR NOT NULL, 
	speaker_label VARCHAR NOT NULL, 
	user_id VARCHAR, 
	is_confirmed BOOLEAN NOT NULL, 
	confidence VARCHAR, 
	notes TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE tasks (
	company_id VARCHAR NOT NULL, 
	meeting_id VARCHAR NOT NULL, 
	assignee_id VARCHAR, 
	title VARCHAR NOT NULL, 
	description TEXT, 
	status VARCHAR NOT NULL, 
	due_date TIMESTAMP WITH TIME ZONE, 
	project_id VARCHAR, 
	priority VARCHAR, 
	deadline TIMESTAMP WITH TIME ZONE, 
	estimated_hours VARCHAR, 
	source_segment_id VARCHAR, 
	source_start_ms FLOAT, 
	source_end_ms FLOAT, 
	speaker_label VARCHAR, 
	extracted_by VARCHAR, 
	extraction_confidence VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE topics (
	company_id VARCHAR NOT NULL, 
	meeting_id VARCHAR, 
	name VARCHAR NOT NULL, 
	description TEXT, 
	importance VARCHAR, 
	extracted_by VARCHAR, 
	extraction_confidence VARCHAR, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE transcript_segments (
	meeting_id VARCHAR NOT NULL, 
	recording_id VARCHAR, 
	segment_id VARCHAR, 
	speaker_label VARCHAR NOT NULL, 
	user_id VARCHAR, 
	speaker_user_id VARCHAR, 
	participant_id UUID, 
	speaker_confirmed BOOLEAN NOT NULL, 
	attribution_status VARCHAR NOT NULL, 
	start_time FLOAT NOT NULL, 
	end_time FLOAT NOT NULL, 
	text VARCHAR NOT NULL, 
	translated_text VARCHAR, 
	language VARCHAR, 
	confidence FLOAT, 
	words JSON, 
	processing_metadata JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_transcript_segment_meeting_segid UNIQUE (meeting_id, segment_id)
)

;

CREATE TABLE unresolved_issues (
	project_id VARCHAR NOT NULL, 
	first_detected_meeting_id VARCHAR NOT NULL, 
	latest_meeting_id VARCHAR NOT NULL, 
	title VARCHAR NOT NULL, 
	description TEXT, 
	status VARCHAR NOT NULL, 
	priority VARCHAR, 
	related_meetings TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE users (
	public_id VARCHAR NOT NULL, 
	firebase_uid VARCHAR, 
	email VARCHAR NOT NULL, 
	hashed_password VARCHAR, 
	full_name VARCHAR, 
	phone VARCHAR, 
	avatar_url VARCHAR, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	account_type VARCHAR NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

CREATE TABLE audit_logs (
	company_id UUID NOT NULL, 
	user_id UUID, 
	action VARCHAR NOT NULL, 
	entity_type VARCHAR NOT NULL, 
	entity_id VARCHAR NOT NULL, 
	details JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
)

;
CREATE UNIQUE INDEX ix_ai_jobs_public_id ON ai_jobs (public_id);
CREATE INDEX ix_ai_jobs_requested_by_user_id ON ai_jobs (requested_by_user_id);
CREATE INDEX ix_ai_jobs_company_id ON ai_jobs (company_id);
CREATE INDEX ix_ai_jobs_status ON ai_jobs (status);
CREATE INDEX ix_ai_jobs_meeting_id ON ai_jobs (meeting_id);
CREATE INDEX ix_ai_jobs_recording_id ON ai_jobs (recording_id);
CREATE INDEX ix_ai_jobs_id ON ai_jobs (id);
CREATE INDEX ix_commitments_source_segment_id ON commitments (source_segment_id);
CREATE INDEX ix_commitments_id ON commitments (id);
CREATE INDEX ix_commitments_project_id ON commitments (project_id);
CREATE INDEX ix_commitments_participant_id ON commitments (participant_id);
CREATE INDEX ix_commitments_meeting_id ON commitments (meeting_id);
CREATE UNIQUE INDEX ix_companies_public_id ON companies (public_id);
CREATE INDEX ix_companies_domain ON companies (domain);
CREATE INDEX ix_companies_id ON companies (id);
CREATE UNIQUE INDEX ix_companies_workspace_code ON companies (workspace_code);
CREATE INDEX ix_company_members_company_id ON company_members (company_id);
CREATE INDEX ix_company_members_user_id ON company_members (user_id);
CREATE INDEX ix_company_members_id ON company_members (id);
CREATE UNIQUE INDEX ix_decision_history_public_id ON decision_history (public_id);
CREATE INDEX ix_decision_history_decision_id ON decision_history (decision_id);
CREATE INDEX ix_decision_history_meeting_id ON decision_history (meeting_id);
CREATE INDEX ix_decision_history_id ON decision_history (id);
CREATE INDEX ix_decisions_source_segment_id ON decisions (source_segment_id);
CREATE INDEX ix_decisions_id ON decisions (id);
CREATE INDEX ix_decisions_project_id ON decisions (project_id);
CREATE INDEX ix_decisions_proposer_id ON decisions (proposer_id);
CREATE INDEX ix_decisions_company_id ON decisions (company_id);
CREATE INDEX ix_decisions_meeting_id ON decisions (meeting_id);
CREATE UNIQUE INDEX ix_document_pages_public_id ON document_pages (public_id);
CREATE INDEX ix_document_pages_document_id ON document_pages (document_id);
CREATE INDEX ix_document_pages_id ON document_pages (id);
CREATE UNIQUE INDEX ix_documents_public_id ON documents (public_id);
CREATE INDEX ix_documents_company_id ON documents (company_id);
CREATE INDEX ix_documents_uploader_id ON documents (uploader_id);
CREATE INDEX ix_documents_id ON documents (id);
CREATE INDEX ix_documents_project_id ON documents (project_id);
CREATE INDEX ix_documents_meeting_id ON documents (meeting_id);
CREATE INDEX ix_embeddings_participant_id ON embeddings (participant_id);
CREATE INDEX ix_embeddings_meeting_id ON embeddings (meeting_id);
CREATE INDEX ix_embeddings_source_type ON embeddings (source_type);
CREATE INDEX ix_embeddings_id ON embeddings (id);
CREATE INDEX ix_embeddings_company_id ON embeddings (company_id);
CREATE INDEX ix_embeddings_source_id ON embeddings (source_id);
CREATE UNIQUE INDEX ix_embeddings_public_id ON embeddings (public_id);
CREATE INDEX ix_embeddings_project_id ON embeddings (project_id);
CREATE INDEX ix_evidence_topic_id ON evidence (topic_id);
CREATE INDEX ix_evidence_task_id ON evidence (task_id);
CREATE INDEX ix_evidence_commitment_id ON evidence (commitment_id);
CREATE INDEX ix_evidence_user_id ON evidence (user_id);
CREATE INDEX ix_evidence_evidence_type ON evidence (evidence_type);
CREATE INDEX ix_evidence_question_id ON evidence (question_id);
CREATE INDEX ix_evidence_unresolved_issue_id ON evidence (unresolved_issue_id);
CREATE INDEX ix_evidence_meeting_id ON evidence (meeting_id);
CREATE INDEX ix_evidence_transcript_segment_id ON evidence (transcript_segment_id);
CREATE INDEX ix_evidence_decision_id ON evidence (decision_id);
CREATE INDEX ix_evidence_risk_id ON evidence (risk_id);
CREATE INDEX ix_evidence_id ON evidence (id);
CREATE INDEX ix_meeting_participants_user_id ON meeting_participants (user_id);
CREATE INDEX ix_meeting_participants_livekit_identity ON meeting_participants (livekit_identity);
CREATE INDEX ix_meeting_participants_id ON meeting_participants (id);
CREATE INDEX ix_meeting_participants_meeting_id ON meeting_participants (meeting_id);
CREATE INDEX ix_meeting_recordings_company_id ON meeting_recordings (company_id);
CREATE INDEX ix_meeting_recordings_processing_status ON meeting_recordings (processing_status);
CREATE INDEX ix_meeting_recordings_id ON meeting_recordings (id);
CREATE INDEX ix_meeting_recordings_meeting_id ON meeting_recordings (meeting_id);
CREATE INDEX ix_meeting_recordings_egress_id ON meeting_recordings (egress_id);
CREATE UNIQUE INDEX ix_meeting_recordings_storage_path ON meeting_recordings (storage_path);
CREATE INDEX ix_meeting_recordings_uploaded_by_user_id ON meeting_recordings (uploaded_by_user_id);
CREATE INDEX ix_meeting_recordings_session_id ON meeting_recordings (session_id);
CREATE INDEX ix_meeting_recordings_deleted_at ON meeting_recordings (deleted_at);
CREATE INDEX ix_meeting_recordings_company_meeting ON meeting_recordings (company_id, meeting_id);
CREATE INDEX ix_meeting_summaries_company_id ON meeting_summaries (company_id);
CREATE INDEX ix_meeting_summaries_id ON meeting_summaries (id);
CREATE UNIQUE INDEX ix_meeting_summaries_meeting_id ON meeting_summaries (meeting_id);
CREATE INDEX ix_meeting_topics_topic_id ON meeting_topics (topic_id);
CREATE INDEX ix_meeting_topics_id ON meeting_topics (id);
CREATE INDEX ix_meeting_topics_company_id ON meeting_topics (company_id);
CREATE INDEX ix_meeting_topics_meeting_id ON meeting_topics (meeting_id);
CREATE INDEX ix_meetings_owner_id ON meetings (owner_id);
CREATE UNIQUE INDEX ix_meetings_public_id ON meetings (public_id);
CREATE INDEX ix_meetings_company_id ON meetings (company_id);
CREATE INDEX ix_meetings_id ON meetings (id);
CREATE UNIQUE INDEX ix_meetings_invite_code ON meetings (invite_code);
CREATE INDEX ix_meetings_project_id ON meetings (project_id);
CREATE INDEX ix_project_members_project_id ON project_members (project_id);
CREATE INDEX ix_project_members_id ON project_members (id);
CREATE INDEX ix_project_members_user_id ON project_members (user_id);
CREATE INDEX ix_projects_company_id ON projects (company_id);
CREATE UNIQUE INDEX ix_projects_public_id ON projects (public_id);
CREATE INDEX ix_projects_id ON projects (id);
CREATE INDEX ix_questions_meeting_id ON questions (meeting_id);
CREATE INDEX ix_questions_source_segment_id ON questions (source_segment_id);
CREATE INDEX ix_questions_asked_by_participant_id ON questions (asked_by_participant_id);
CREATE INDEX ix_questions_mentioned_to_participant_id ON questions (mentioned_to_participant_id);
CREATE INDEX ix_questions_project_id ON questions (project_id);
CREATE INDEX ix_questions_id ON questions (id);
CREATE INDEX ix_reminders_commitment_id ON reminders (commitment_id);
CREATE INDEX ix_reminders_id ON reminders (id);
CREATE INDEX ix_reminders_user_id ON reminders (user_id);
CREATE INDEX ix_reminders_action_item_id ON reminders (action_item_id);
CREATE INDEX ix_risks_id ON risks (id);
CREATE INDEX ix_risks_owner_participant_id ON risks (owner_participant_id);
CREATE INDEX ix_risks_source_segment_id ON risks (source_segment_id);
CREATE INDEX ix_risks_meeting_id ON risks (meeting_id);
CREATE INDEX ix_risks_project_id ON risks (project_id);
CREATE INDEX ix_speaker_mappings_user_id ON speaker_mappings (user_id);
CREATE INDEX ix_speaker_mappings_id ON speaker_mappings (id);
CREATE INDEX ix_speaker_mappings_speaker_label ON speaker_mappings (speaker_label);
CREATE INDEX ix_speaker_mappings_meeting_id ON speaker_mappings (meeting_id);
CREATE INDEX ix_tasks_company_id ON tasks (company_id);
CREATE INDEX ix_tasks_meeting_id ON tasks (meeting_id);
CREATE INDEX ix_tasks_source_segment_id ON tasks (source_segment_id);
CREATE INDEX ix_tasks_id ON tasks (id);
CREATE INDEX ix_tasks_assignee_id ON tasks (assignee_id);
CREATE INDEX ix_tasks_project_id ON tasks (project_id);
CREATE INDEX ix_topics_company_id ON topics (company_id);
CREATE INDEX ix_topics_meeting_id ON topics (meeting_id);
CREATE INDEX ix_topics_name ON topics (name);
CREATE INDEX ix_topics_id ON topics (id);
CREATE INDEX ix_transcript_segments_id ON transcript_segments (id);
CREATE INDEX ix_transcript_segments_meeting_start ON transcript_segments (meeting_id, start_time);
CREATE INDEX ix_transcript_segments_participant ON transcript_segments (meeting_id, participant_id);
CREATE INDEX ix_transcript_segments_speaker_user_id ON transcript_segments (speaker_user_id);
CREATE INDEX ix_transcript_segments_participant_id ON transcript_segments (participant_id);
CREATE INDEX ix_transcript_segments_segment_id ON transcript_segments (segment_id);
CREATE INDEX ix_transcript_segments_user_id ON transcript_segments (user_id);
CREATE INDEX ix_transcript_segments_speaker_user ON transcript_segments (meeting_id, speaker_user_id);
CREATE INDEX ix_transcript_segments_meeting_id ON transcript_segments (meeting_id);
CREATE INDEX ix_transcript_segments_recording_id ON transcript_segments (recording_id);
CREATE INDEX ix_unresolved_issues_latest_meeting_id ON unresolved_issues (latest_meeting_id);
CREATE INDEX ix_unresolved_issues_id ON unresolved_issues (id);
CREATE INDEX ix_unresolved_issues_project_id ON unresolved_issues (project_id);
CREATE INDEX ix_users_id ON users (id);
CREATE UNIQUE INDEX ix_users_public_id ON users (public_id);
CREATE UNIQUE INDEX ix_users_firebase_uid ON users (firebase_uid);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE INDEX ix_audit_logs_id ON audit_logs (id);