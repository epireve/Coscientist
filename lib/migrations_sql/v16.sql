-- v0.190 — canonicalize legacy phase aliases in papers_in_run.added_in_phase.
-- The Expedition rebrand (v0.46.4) renamed all 10 phase names; lib aliasing
-- still resolves both, but persisted rows from old runs (and the long-lived
-- merge.py bug) carry pre-rebrand names. Migrate them once.
UPDATE papers_in_run SET added_in_phase = 'scout'        WHERE added_in_phase = 'social';
UPDATE papers_in_run SET added_in_phase = 'cartographer' WHERE added_in_phase = 'grounder';
UPDATE papers_in_run SET added_in_phase = 'chronicler'   WHERE added_in_phase = 'historian';
UPDATE papers_in_run SET added_in_phase = 'surveyor'     WHERE added_in_phase = 'gaper';
UPDATE papers_in_run SET added_in_phase = 'synthesist'   WHERE added_in_phase = 'vision';
UPDATE papers_in_run SET added_in_phase = 'architect'    WHERE added_in_phase = 'theorist';
UPDATE papers_in_run SET added_in_phase = 'inquisitor'   WHERE added_in_phase = 'rude';
UPDATE papers_in_run SET added_in_phase = 'weaver'       WHERE added_in_phase = 'synthesizer';
UPDATE papers_in_run SET added_in_phase = 'visionary'    WHERE added_in_phase = 'thinker';
UPDATE papers_in_run SET added_in_phase = 'steward'      WHERE added_in_phase = 'scribe';
