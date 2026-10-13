-- Additive Phase 2 migration; no business records are deleted or rewritten.
BEGIN;

SELECT pg_advisory_xact_lock(71012025);

ALTER TABLE medicines ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(120);

ALTER TABLE distributors ADD COLUMN IF NOT EXISTS contact_email VARCHAR(254);

ALTER TABLE inventory ADD COLUMN IF NOT EXISTS is_sellable BOOLEAN;

CREATE TABLE IF NOT EXISTS dq_datasets (
	name VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	metadata_json JSON NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (name), 
	CHECK (version > 0), 
	CHECK (status IN ('staged','validated','quarantined','approved'))
);

CREATE TABLE IF NOT EXISTS dq_schema_migrations (
	version SERIAL NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	applied_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS dq_staging_records (
	id SERIAL NOT NULL, 
	dataset VARCHAR(64) NOT NULL, 
	entity VARCHAR(30) NOT NULL, 
	record_ref VARCHAR(80) NOT NULL, 
	payload JSON NOT NULL, 
	quarantined BOOLEAN NOT NULL, 
	is_deleted BOOLEAN NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (dataset, entity, record_ref), 
	FOREIGN KEY(dataset) REFERENCES dq_datasets (name)
);

CREATE INDEX IF NOT EXISTS ix_dq_staging_records_dataset ON dq_staging_records (dataset);

CREATE TABLE IF NOT EXISTS dq_validation_runs (
	id SERIAL NOT NULL, 
	dataset VARCHAR(64) NOT NULL, 
	dataset_version INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	config_json JSON NOT NULL, 
	report_json JSON NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	reference_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	overall_score NUMERIC(10, 6), 
	failed_records INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset) REFERENCES dq_datasets (name)
);

CREATE INDEX IF NOT EXISTS ix_dq_validation_runs_dataset ON dq_validation_runs (dataset);

CREATE TABLE IF NOT EXISTS dq_issues (
	id SERIAL NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	dataset VARCHAR(64) NOT NULL, 
	rule_id VARCHAR(20) NOT NULL, 
	rule_version VARCHAR(20) NOT NULL, 
	entity VARCHAR(30) NOT NULL, 
	record_ref VARCHAR(80) NOT NULL, 
	field VARCHAR(80) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	description TEXT NOT NULL, 
	remediation TEXT NOT NULL, 
	medicine_ref VARCHAR(80), 
	batch_ref VARCHAR(80), 
	first_run_id INTEGER NOT NULL, 
	last_run_id INTEGER NOT NULL, 
	detected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	resolution_notes TEXT, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CHECK (severity IN ('critical','error','warning')), 
	CHECK (status IN ('open','acknowledged','resolved','false_positive')), 
	UNIQUE (fingerprint), 
	FOREIGN KEY(dataset) REFERENCES dq_datasets (name), 
	FOREIGN KEY(first_run_id) REFERENCES dq_validation_runs (id), 
	FOREIGN KEY(last_run_id) REFERENCES dq_validation_runs (id)
);

CREATE INDEX IF NOT EXISTS ix_dq_issues_dataset ON dq_issues (dataset);

CREATE INDEX IF NOT EXISTS ix_dq_issues_status ON dq_issues (status);

CREATE TABLE IF NOT EXISTS dq_audit_events (
	id SERIAL NOT NULL, 
	dataset VARCHAR(64) NOT NULL, 
	issue_id INTEGER, 
	action VARCHAR(40) NOT NULL, 
	actor VARCHAR(100) NOT NULL, 
	notes TEXT NOT NULL, 
	before_json JSON, 
	after_json JSON, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(dataset) REFERENCES dq_datasets (name), 
	FOREIGN KEY(issue_id) REFERENCES dq_issues (id)
);

CREATE INDEX IF NOT EXISTS ix_dq_audit_events_dataset ON dq_audit_events (dataset);

CREATE TABLE IF NOT EXISTS dq_run_findings (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	issue_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, issue_id), 
	FOREIGN KEY(run_id) REFERENCES dq_validation_runs (id), 
	FOREIGN KEY(issue_id) REFERENCES dq_issues (id)
);

CREATE INDEX IF NOT EXISTS ix_dq_run_findings_run_id ON dq_run_findings (run_id);

INSERT INTO dq_schema_migrations (version,name) VALUES (2,'Phase 2 staging, validation and audit') ON CONFLICT (version) DO NOTHING;

COMMIT;
