-- Additive Phase 3 migration; apply after 001 and 002. All data is synthetic.

BEGIN;

SELECT pg_advisory_xact_lock(71012025);


CREATE TABLE IF NOT EXISTS auto_alerts (
	id SERIAL NOT NULL, 
	identity VARCHAR(160) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	reason TEXT NOT NULL, 
	record_ids JSON NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	revision INTEGER NOT NULL, 
	notified_revision INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	detected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CHECK (status IN ('new','acknowledged','resolved')), 
	CHECK (severity IN ('critical','error','warning')), 
	UNIQUE (identity)
)

;

CREATE INDEX IF NOT EXISTS ix_auto_alerts_kind ON auto_alerts (kind);

CREATE INDEX IF NOT EXISTS ix_auto_alerts_status ON auto_alerts (status);


CREATE TABLE IF NOT EXISTS auto_executions (
	id VARCHAR(36) NOT NULL, 
	idempotency_key VARCHAR(160) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	actor VARCHAR(100) NOT NULL, 
	notes TEXT NOT NULL, 
	config_json JSON NOT NULL, 
	params_json JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	duration_seconds FLOAT, 
	attempts INTEGER NOT NULL, 
	error_type VARCHAR(80), 
	result_json JSON, 
	PRIMARY KEY (id), 
	CHECK (kind IN ('daily','weekly')), 
	CHECK (status IN ('queued','running','succeeded','failed','timed_out')), 
	UNIQUE (idempotency_key)
)

;

CREATE INDEX IF NOT EXISTS ix_auto_executions_status ON auto_executions (status);


CREATE TABLE IF NOT EXISTS auto_scheduler_state (
	id VARCHAR(20) NOT NULL, 
	owner VARCHAR(36) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	jobs_json JSON NOT NULL, 
	config_json JSON NOT NULL, 
	PRIMARY KEY (id)
)

;


CREATE TABLE IF NOT EXISTS auto_alert_events (
	id SERIAL NOT NULL, 
	alert_id INTEGER NOT NULL, 
	action VARCHAR(30) NOT NULL, 
	actor VARCHAR(100) NOT NULL, 
	notes TEXT NOT NULL, 
	before_json JSON, 
	after_json JSON, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(alert_id) REFERENCES auto_alerts (id)
)

;

CREATE INDEX IF NOT EXISTS ix_auto_alert_events_alert_id ON auto_alert_events (alert_id);


CREATE TABLE IF NOT EXISTS auto_attempts (
	id SERIAL NOT NULL, 
	execution_id VARCHAR(36) NOT NULL, 
	number INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	duration_seconds FLOAT, 
	error_type VARCHAR(80), 
	PRIMARY KEY (id), 
	UNIQUE (execution_id, number), 
	FOREIGN KEY(execution_id) REFERENCES auto_executions (id)
)

;

CREATE INDEX IF NOT EXISTS ix_auto_attempts_execution_id ON auto_attempts (execution_id);


CREATE TABLE IF NOT EXISTS auto_emails (
	id VARCHAR(36) NOT NULL, 
	execution_id VARCHAR(36) NOT NULL, 
	filename VARCHAR(100) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	subject TEXT NOT NULL, 
	body_text TEXT NOT NULL, 
	recipients_json JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	attempts INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	delivered_at TIMESTAMP WITH TIME ZONE, 
	error_type VARCHAR(80), 
	PRIMARY KEY (id), 
	CHECK (status IN ('preview','queued','sending','sent','failed','uncertain')), 
	UNIQUE (execution_id), 
	FOREIGN KEY(execution_id) REFERENCES auto_executions (id), 
	UNIQUE (filename)
)

;


CREATE TABLE IF NOT EXISTS auto_events (
	id SERIAL NOT NULL, 
	execution_id VARCHAR(36), 
	stage VARCHAR(30) NOT NULL, 
	event VARCHAR(50) NOT NULL, 
	details_json JSON NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(execution_id) REFERENCES auto_executions (id)
)

;

CREATE INDEX IF NOT EXISTS ix_auto_events_execution_id ON auto_events (execution_id);


CREATE TABLE IF NOT EXISTS auto_reports (
	id VARCHAR(36) NOT NULL, 
	execution_id VARCHAR(36) NOT NULL, 
	filename VARCHAR(100) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	byte_size INTEGER NOT NULL, 
	snapshot_hash VARCHAR(64) NOT NULL, 
	summary_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (execution_id), 
	FOREIGN KEY(execution_id) REFERENCES auto_executions (id), 
	UNIQUE (filename)
)

;


CREATE TABLE IF NOT EXISTS auto_mail_events (
	id SERIAL NOT NULL, 
	email_id VARCHAR(36) NOT NULL, 
	attempt INTEGER NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	error_type VARCHAR(80), 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(email_id) REFERENCES auto_emails (id)
)

;

INSERT INTO dq_schema_migrations (version,name) VALUES (3,'Phase 3 reporting, jobs and alerts') ON CONFLICT (version) DO NOTHING;

COMMIT;
