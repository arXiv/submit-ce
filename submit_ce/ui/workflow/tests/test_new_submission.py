"""Tests for workflow"""

from submit_ce.ui import workflow
from submit_ce.ui.auth import user_and_client_from_session
from submit_ce.ui.tests import CtrlBase
from submit_ce.ui.workflow import processor
from submit_ce.api.domain.event import CreateSubmission
from submit_ce.ui.workflow.stages import *
from submit_ce.api.domain import SubmissionContent, SubmissionMetadata
import pytest

@pytest.mark.skip
class TestNewSubmissionWorkflow(CtrlBase):

    def testWorkflowGetitem(self):
        wf = workflow.WorkflowDefinition(
            name='TestingWorkflow',
            order=[VerifyUser(), Agreement(), FinalPreview()])

        self.assertIsNotNone(wf[VerifyUser])
        self.assertEqual(wf[VerifyUser].__class__, VerifyUser)
        self.assertEqual(wf[0].__class__, VerifyUser)

        self.assertEqual(wf[VerifyUser], wf[0])
        self.assertEqual(wf[VerifyUser], wf['VerifyUser'])
        self.assertEqual(wf[VerifyUser], wf['verify_user'])
        self.assertEqual(wf[VerifyUser], wf[wf.order[0]])

        self.assertEqual(next(wf.iter_prior(wf[Agreement])), wf[VerifyUser])

    def testVerifyUser(self):
        seen = {}
        # submitter = User('Bob', 'FakePants', 'Sponge',
        #                  'bob_id_xy21', 'cornell.edu', 'UNIT_TEST_AGENT')
        user, client = user_and_client_from_session(self.session)
        cevnt = CreateSubmission(creator=user, client=client)
        submission = cevnt.apply(None)

        nswfps = processor.WorkflowProcessor(workflow.NewSubmissionWorkflow,
                                             submission, seen)

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))

        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))        
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[VerifyUser])

        submission.submitter_contact_verified = True
        nswfps.mark_seen(nswfps.workflow[VerifyUser])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))

        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[Authorship])

        submission.submitter_is_author = True
        nswfps.mark_seen(nswfps.workflow[Authorship])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))

        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[License])

        submission.license = "someLicense"
        nswfps.mark_seen(nswfps.workflow[License])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))

        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[Agreement])

        submission.submitter_accepts_policy = True
        nswfps.mark_seen(nswfps.workflow[Agreement])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertTrue(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))

        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(),
                         nswfps.workflow[Classification])

        submission.primary_classification = {'category': "FakePrimaryCategory"}
        nswfps.mark_seen(nswfps.workflow[Classification])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Classification]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        # should be allowed to skip the "cross" but may be a problem with has_seen
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        # TODO this should go to cross becasue of has_seen but has_seen not yet implemented
        #self.assertEqual(nswfps.current_stage(), nswfps.workflow[CrossList])

        submission.secondary_classification = [
            {'category': 'fakeSecondaryCategory'}]
        nswfps.mark_seen(nswfps.workflow[CrossList])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertTrue(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))

        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Process]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[FileUpload])

        submission.source_content = SubmissionContent(
            'identifierX', 'checksum_xyz', 100, 10, SubmissionContent.Format.TEX)        
        nswfps.mark_seen(nswfps.workflow[FileUpload])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertTrue(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Process]))
        
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[Process])

        #Now try a PDF upload
        submission.source_content = SubmissionContent(
            'identifierX', 'checksum_xyz', 100, 10, SubmissionContent.Format.PDF)
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Process]))        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Metadata]))
        
        self.assertFalse(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))
        self.assertEqual(nswfps.current_stage(), nswfps.workflow[Metadata])
               
        submission.metadata = SubmissionMetadata(title="FakeOFakeyDuFakeFake",
                                                 abstract="I like it.",
                                                 authors_display="Bob Fakeyfake")
        nswfps.mark_seen(nswfps.workflow[Metadata])

        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Classification]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Process]))        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Metadata]))        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[OptionalMetadata]))

        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        self.assertEqual(nswfps.current_stage(), nswfps.workflow[OptionalMetadata])

        #optional metadata only seen
        nswfps.mark_seen(nswfps.workflow[OptionalMetadata])  
        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        
        self.assertFalse(nswfps.can_proceed_to(nswfps.workflow.confirmation))

        submission.status = 'submitted'
        nswfps.mark_seen(nswfps.workflow[FinalPreview])
        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[VerifyUser]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Authorship]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[License]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Agreement]))
        self.assertTrue(nswfps.can_proceed_to(
            nswfps.workflow[Classification]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[CrossList]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FileUpload]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Process]))        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[Metadata]))        
        self.assertTrue(nswfps.can_proceed_to(
            nswfps.workflow[OptionalMetadata]))        
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow[FinalPreview]))
        self.assertTrue(nswfps.can_proceed_to(nswfps.workflow.confirmation))
