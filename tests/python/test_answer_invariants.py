"""Import-level counterexamples for the four answer-channel invariants; no AI or MATLAB."""
from pathlib import Path
import json
import unittest
from unittest import mock

import test_answer_edges as fixtures
from matlab_harness import answer as channel
from matlab_harness.project import ReviewProtocolError
from matlab_harness.workflow import packet, submit_answer


class AnswerInvariantTests(unittest.TestCase):
    setUp = fixtures.AnswerEdgeTests.setUp
    seed = fixtures.AnswerEdgeTests.seed
    translate = fixtures.AnswerEdgeTests.translate

    def test_dot_artifact_preserves_serious_claim_instead_of_crashing_import(self):
        with self.project.transaction('owner') as data:
            data['phase'] = 'implementation'
        packet(self.project, 'reviewer')
        reply = {'verdict': 'REJECT', 'findings': [fixtures.ISSUE], 'traceability': fixtures.ROWS,
                 'checks': [{'id': 'CHK-1', 'result': 'PASS', 'artifact': '.'}]}
        with self.assertRaises(ReviewProtocolError):
            submit_answer(self.project, 'owner', reply, 'independent-1', 'test-model')
        self.assertTrue(any(f['finding']['severity'] == 'MAJOR'
                            for f in self.project.pending_review_findings().values()))

    def test_canonical_keys_keep_a_serious_claim_and_block_acceptance(self):
        packet(self.project, 'reviewer')
        reply = {'VERDICT': 'ACCEPT', 'Traceability': fixtures.ROWS,
                 'Findings': [{k.upper(): v for k, v in fixtures.ISSUE.items()}]}
        imported = submit_answer(self.project, 'owner', reply, 'independent-1', 'test-model')
        report = json.loads((self.root / imported['imported']).read_text())
        self.assertEqual([f['severity'] for f in report['findings']], ['MAJOR'])
        self.assertFalse(imported['gate']['accepted'])

    def test_canonical_collisions_keep_weakest_status_and_identical_duplicates(self):
        for second, expected in [('REJECT', 'REJECT'), ('accept', 'ACCEPT')]:
            # A REJECT needs a blocking reason; the issue is that reason, not what is tested here.
            reason = {'findings': [fixtures.ISSUE]} if expected == 'REJECT' else {}
            reply = {'verdict': 'ACCEPT', 'Verdict': second, 'traceability': fixtures.ROWS, **reason}
            record, problems = channel.translate(self.project, self.project.load(), 'requirements', reply, self.scratch)
            self.assertEqual(record['verdict'], expected)
            self.assertEqual(problems, [])
        record, _ = self.translate(self.project.load(), 'requirements', traceability={
            'R-1': {'Status': 'VERIFIED', 'status': 'FAILED', 'Evidence': 'observed failure'},
            'R-2': fixtures.ROWS['R-2']})
        self.assertEqual(record['traceability'][0]['status'], 'FAILED')

    def test_all_roots_are_read_even_below_an_earlier_accept(self):
        nested = {'verdict': 'REJECT', 'findings': [fixtures.ISSUE]}
        for _ in range(12):
            nested = {'wrapper': nested}
        reply = {'verdict': 'ACCEPT', 'traceability': fixtures.ROWS, 'final': nested}
        record, _ = channel.translate(self.project, self.project.load(), 'requirements', reply, self.scratch)
        self.assertEqual(record['verdict'], 'REJECT')
        self.assertEqual([f['severity'] for f in record['findings']], ['MAJOR'])

    def test_keyed_rows_keep_nested_contradictions_beside_metadata_or_an_actual_row(self):
        failed = {'requirement': 'R-1', 'status': 'FAILED', 'evidence': 'probe failed'}
        shapes = [
            {'wrapper': {'evidence': 'group summary', 'rows': [failed]}},
            [{'requirement': 'R-1', 'status': 'VERIFIED', 'evidence': 'outer row', 'rows': [failed]}],
            {'R-1': {'status': 'VERIFIED', 'evidence': 'outer row', 'rows': [failed]}},
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                record, problems = self.translate(self.project.load(), 'requirements', trace=shape)
                self.assertEqual(record['traceability'][0]['status'], 'FAILED')
                self.assertTrue(problems)

    def test_known_handle_takes_precedence_over_a_metadata_field_name(self):
        data = self.seed(issue={**fixtures.ISSUE, 'id': 'status'})
        record, problems = self.translate(data, 'requirements',
            open_items={'status': {'status': 'CLOSED', 'evidence': 'reviewed'}})
        self.assertEqual(problems, [])
        self.assertEqual(record['findings'][0]['status'], 'CLOSED')

    def test_nested_root_serious_claim_binds_on_import(self):
        packet(self.project, 'reviewer')
        reply = {'verdict': 'ACCEPT', 'traceability': fixtures.ROWS,
                 'final': {'verdict': 'REJECT', 'findings': [fixtures.ISSUE]}}
        imported = submit_answer(self.project, 'owner', reply, 'independent-1', 'test-model')
        report = json.loads((self.root / imported['imported']).read_text())
        self.assertEqual(report['verdict'], 'REJECT')
        self.assertTrue(self.project.gate('requirements')['problems'])

    def test_id_only_group_cannot_hide_its_actual_finding(self):
        record, _ = self.translate(self.project.load(), 'requirements', verdict='REJECT',
                                   findings=[{'id': 'group', 'members': [fixtures.ISSUE]}])
        self.assertEqual([(f['id'], f['evidence']) for f in record['findings']],
                         [('F-1', fixtures.ISSUE['evidence'])])

    def test_nested_container_beside_an_entry_also_retains_its_claim(self):
        record, _ = self.translate(self.project.load(), 'requirements', verdict='REJECT', findings=[{
            **fixtures.ISSUE, 'members': [{**fixtures.ISSUE, 'id': 'F-2', 'severity': 'CRITICAL'}]}])
        self.assertEqual({f['severity'] for f in record['findings']}, {'MAJOR', 'CRITICAL'})

    def test_same_probe_fail_vetoes_closure_by_file_and_by_passing_check_id(self):
        data = self.seed('implementation')
        (self.scratch / 'probe_adversarial.m').write_text('assert(false)')
        checks = [{'id': 'CHK-ET5', 'result': 'PASS', 'artifact': 'probe_adversarial.m'},
                  {'id': 'CHK-ET7-R0', 'result': 'FAIL',
                   'artifact': str(self.scratch / 'probe_adversarial.m')}]
        for evidence in ('probe_adversarial.m', 'CHK-ET5'):
            record, problems = self.translate(data, 'implementation', independent_checks=checks,
                open_items={'F-1': {'status': 'CLOSED', 'evidence': evidence}})
            self.assertTrue(any('not closed: F-1' in p for p in problems), evidence)
        checks.pop()
        _, problems = self.translate(data, 'implementation', independent_checks=checks,
            open_items={'F-1': {'status': 'CLOSED', 'evidence': 'CHK-ET5'}})
        self.assertEqual(problems, [])

    def test_same_file_failure_keeps_a_new_closed_serious_finding_open(self):
        (self.scratch / 'p.m').write_text('assert(false)')
        record, _ = self.translate(self.project.load(), 'implementation', verdict='REJECT',
            independent_checks=[{'id': 'C-1', 'result': 'PASS', 'artifact': 'p.m'},
                                {'id': 'C-2', 'result': 'FAIL', 'artifact': 'scratch/p.m'}],
            findings=[{**fixtures.ISSUE, 'status': 'CLOSED', 'closure': 'p.m passed'}])
        self.assertEqual(record['findings'][0]['status'], 'OPEN')

    def test_proof_and_check_use_the_same_project_first_path_resolution(self):
        data = self.seed('implementation')
        (self.scratch / 'src').mkdir()
        copy = self.scratch / 'src/f.m'
        copy.write_text('independent scratch copy')
        checks = [{'id': 'CHK-1', 'result': 'PASS', 'artifact': str(copy)}]
        _, problems = self.translate(data, 'implementation', independent_checks=checks,
            open_items={'F-1': {'status': 'CLOSED', 'evidence': 'src/f.m'}})
        self.assertTrue(any('not closed: F-1' in p for p in problems))
        _, problems = self.translate(data, 'implementation', independent_checks=checks,
            open_items={'F-1': {'status': 'CLOSED', 'evidence': str(copy)}})
        self.assertEqual(problems, [])

    def test_failure_of_a_different_probe_does_not_poison_a_passing_file(self):
        data = self.seed('implementation')
        for name in ('p.m', 'q.m'):
            (self.scratch / name).write_text('independent probe')
        _, problems = self.translate(data, 'implementation', independent_checks=[
            {'id': 'C-1', 'result': 'PASS', 'artifact': 'p.m'},
            {'id': 'C-2', 'result': 'FAIL', 'artifact': 'q.m'}],
            open_items={'F-1': {'status': 'CLOSED', 'evidence': 'p.m'}})
        self.assertEqual(problems, [])

    def test_severity_labels_never_hide_more_serious_prose(self):
        for finding in ({**fixtures.ISSUE, 'severity': 'MINOR', 'evidence': 'CRITICAL: f(0) crashes'},
                        '[MINOR] CRITICAL: f(0) crashes'):
            record, _ = self.translate(self.project.load(), 'requirements', verdict='REJECT', findings=[finding])
            self.assertEqual(record['findings'][0]['severity'], 'CRITICAL')
        self.assertEqual(channel._severity('MINOR: typo in the major-axis code'), 'MINOR')

    def test_size_admission_covers_traceability_and_unknown_fields(self):
        for field, value in [('traceability', [fixtures.ROWS] * 40 + [{'R-1': {'status': 'FAILED'}}]),
                             ('unknown', ['x'] * 40)]:
            with mock.patch.object(channel, 'BUDGET', 32):
                record, problems = self.translate(self.project.load(), 'requirements', **{field: value})
            self.assertTrue(problems)
            self.assertNotEqual(record['verdict'], 'ACCEPT')
            self.assertTrue(any(f['severity'] in {'MAJOR', 'CRITICAL'} for f in record['findings']))

    def test_oversize_refusal_binds_a_durable_unexamined_answer_condition(self):
        packet(self.project, 'reviewer')
        with mock.patch.object(channel, 'BUDGET', 32):
            with self.assertRaises(ReviewProtocolError):
                submit_answer(self.project, 'owner', {'verdict': 'ACCEPT', 'traceability': fixtures.ROWS,
                    'findings': ['none'] * 40 + ['CRITICAL: unread tail']}, 'independent-1', 'test-model')
        self.assertTrue(self.project.pending_review_findings())
        with self.assertRaises(ReviewProtocolError):
            submit_answer(self.project, 'owner', {'verdict': 'ACCEPT', 'traceability': fixtures.ROWS},
                          'independent-2', 'test-model')
        self.assertTrue(self.project.pending_review_findings())

    def test_text_size_is_bounded_before_normalization(self):
        with mock.patch.object(channel, 'TEXT_BUDGET', 32, create=True):
            record, problems = self.translate(self.project.load(), 'requirements', unknown='x' * 40)
        self.assertTrue(problems)
        self.assertNotEqual(record['verdict'], 'ACCEPT')

    def test_every_named_artifact_is_read_before_a_file_can_prove_closure(self):
        data = self.seed('implementation')
        names = [f'p{i}.m' for i in range(21)]
        for name in names:
            (self.scratch / name).write_text('independent probe')
        _, problems = self.translate(data, 'implementation', independent_checks=[
            {'id': 'CHK-P', 'result': 'PASS', 'artifact': names[-1]},
            {'id': 'CHK-F', 'result': 'FAIL', 'artifact': ' '.join(names)}],
            open_items={'F-1': {'status': 'CLOSED', 'evidence': names[-1]}})
        self.assertTrue(any('not closed: F-1' in p for p in problems))

    def test_all_prose_aliases_can_raise_severity_and_retain_the_claim(self):
        record, _ = self.translate(self.project.load(), 'requirements', verdict='REJECT', findings=[{
            **fixtures.ISSUE, 'severity': 'MINOR', 'evidence': 'typo', 'description': 'CRITICAL: crash'}])
        self.assertEqual(record['findings'][0]['severity'], 'CRITICAL')
        self.assertIn('CRITICAL: crash', record['findings'][0]['evidence'])

    def test_scalar_metadata_of_an_actual_finding_does_not_invent_another_claim(self):
        record, problems = self.translate(self.project.load(), 'requirements', verdict='REJECT',
            findings=[{**fixtures.ISSUE, 'author': 'Alice', 'extra': 3}])
        self.assertEqual(len(record['findings']), 1)
        self.assertEqual(record['findings'][0]['evidence'], fixtures.ISSUE['evidence'])
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main()
