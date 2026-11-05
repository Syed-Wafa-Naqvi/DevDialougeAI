class InvalidStateTransitionError(ValueError):
    """Raised when an illegal session state machine transition is attempted."""
    pass

class SessionStateMachine:
    STATES = {
        'interviewing': 'Requirement Elicitation',
        'srs_ready': 'SRS Synthesized',
        'plan_draft': 'Plan Generated (Awaiting Approval)',
        'plan_approved': 'Plan Approved',
        'generating': 'Generating Source Code',
        'verifying': 'Verifying Codebase',
        'repairing': 'Repairing Issues',
        'awaiting_review': 'Awaiting Module Review (Mode 2)',
        'applying_feedback': 'Applying Feedback / Editing',
        'ready': 'Codebase Verified & Ready',
        'needs_attention': 'Unverified Issues Remain',
    }

    # Allowed state transition map: current_state -> set of allowed next_states
    TRANSITIONS = {
        'interviewing': {'interviewing', 'srs_ready', 'plan_draft', 'plan_approved', 'generating', 'active'},
        'active': {'interviewing', 'srs_ready', 'plan_draft', 'plan_approved', 'generating', 'active'},  # Backward compatibility
        'srs_ready': {'plan_draft', 'plan_approved', 'generating', 'interviewing'},
        'plan_draft': {'plan_draft', 'plan_approved', 'interviewing', 'generating'},
        'plan_approved': {'generating', 'plan_draft', 'interviewing'},
        'generating': {'verifying', 'awaiting_review', 'generating', 'needs_attention', 'ready', 'srs_ready'},
        'verifying': {'repairing', 'ready', 'needs_attention', 'generating'},
        'repairing': {'verifying', 'ready', 'needs_attention'},
        'awaiting_review': {'generating', 'applying_feedback', 'ready', 'completed'},
        'applying_feedback': {'verifying', 'generating'},
        'ready': {'applying_feedback', 'interviewing', 'completed', 'generating', 'srs_ready'},
        'needs_attention': {'applying_feedback', 'repairing', 'interviewing', 'completed', 'generating', 'srs_ready'},
        'completed': {'applying_feedback', 'interviewing', 'ready', 'active', 'srs_ready', 'plan_draft', 'generating'},
    }

    @classmethod
    def transition_to(cls, session, new_state: str):
        """
        Enforces explicit session state transitions.
        Raises InvalidStateTransitionError if transition is prohibited.
        """
        current_state = session.status
        if current_state == new_state:
            return

        allowed = cls.TRANSITIONS.get(current_state, set())
        # If unknown current state, allow transition to interviewing or initial states
        if current_state not in cls.TRANSITIONS:
            allowed = {'interviewing', 'srs_ready', 'plan_draft', 'generating', 'ready'}

        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition session {session.id} from state '{current_state}' to '{new_state}'."
            )

        session.status = new_state
        session.save(update_fields=['status'])
