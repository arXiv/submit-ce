"""Tests for the submission UI domain classes."""

# Commenting out for now - there is nothing that runs below - everything
# is commented out - dlf2
#from .. import domain


# class TestSubmissionStage(TestCase):
#     """Tests for :class:`domain.SubmissionStage`."""
#
#     def test_initial_stage(self):
#         """Nothing has been done yet."""
#         submission = Submission(
#             creator=User('12345', 'foo@user.edu'),
#             owner=User('12345', 'foo@user.edu'),
#             created=datetime.now()
#         )
#         submission_stage = domain.SubmissionStage(submission)
#         self.assertEqual(submission_stage.current_stage, None,
#                          "No stage is complete.")
#         self.assertEqual(submission_stage.next_stage,
#                          domain.SubmissionStage.ORDER[0][0],
#                          "The next stage is the first stage.")
#         self.assertIsNone(submission_stage.previous_stage,
#                           "There is no previous stage.")
#
#         self.assertTrue(
#             submission_stage.before(domain.Stages.POLICY)
#         )
#         self.assertTrue(
#             submission_stage.on_or_before(domain.Stages.POLICY)
#         )
#         self.assertTrue(
#             submission_stage.on_or_before(submission_stage.current_stage)
#         )
#         self.assertFalse(
#             submission_stage.after(domain.Stages.POLICY)
#         )
#         self.assertFalse(
#             submission_stage.on_or_after(domain.Stages.POLICY)
#         )
#         self.assertTrue(
#             submission_stage.on_or_after(submission_stage.current_stage)
#         )
#
#     def test_verify(self):
#         """The user has verified their information."""
#         submission = Submission(
#             creator=User('12345', 'foo@user.edu'),
#             owner=User('12345', 'foo@user.edu'),
#             created=datetime.now(),
#             submitter_contact_verified=True
#         )
#         submission_stage = domain.SubmissionStage(submission)
#         self.assertEqual(submission_stage.previous_stage, None,
#                          "There is nothing before the verify user stage")
#         self.assertEqual(submission_stage.next_stage,
#                          domain.Stages.AUTHORSHIP,
#                          "The next stage is to indicate authorship.")
#         self.assertEqual(submission_stage.current_stage,
#                          domain.Stages.VERIFY_USER,
#                          "The current completed stage is verify user.")
