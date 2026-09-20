from __future__ import annotations

from server.services.edit_planner import clean_overlay_text, plan_edit


def test_product_test_instruction_is_fully_deterministic():
    p = plan_edit("Turn this footage into a short vertical UGC ad. Remove awkward pauses, keep the pacing tight, "
                  "add clear captions, and create a clean CTA ending.")
    assert p.remove_silence and p.captions and p.cta_text == "Learn more" and p.speed_all > 1
    assert not p.generative_prompts and not p.needs_agent and p.deterministic_only


def test_revision_instruction():
    p = plan_edit("Make the opening faster and cut the final video shorter.")
    assert p.speed_opening and p.shorten and p.deterministic_only


def test_trim_and_target_duration():
    p = plan_edit("Remove the first 2 seconds and cut it down to 20 seconds")
    assert p.trim_start_seconds == 2.0 and p.target_duration_seconds == 20.0


def test_explicit_target_from_request_used_when_instruction_silent():
    assert plan_edit("Add bold captions please", duration_target_seconds=25).target_duration_seconds == 25.0


def test_local_edits_never_request_generation():
    for text in ("Remove the first 2 seconds", "Add bold captions", "Cut the silence and speed up the pacing",
                 "Put a CTA at the end", "Use the product footage more"):
        p = plan_edit(text)
        assert not p.generative_prompts, text


def test_generation_only_when_new_footage_is_requested():
    p = plan_edit("Tighten the pacing. Generate a new shot of the serum bottle sitting on a marble vanity.")
    assert len(p.generative_prompts) == 1 and "marble vanity" in p.generative_prompts[0]
    assert p.deterministic_only is False


def test_creative_judgement_and_unknown_flag_agent():
    assert plan_edit("Put the product clip after she says serum").needs_agent
    assert plan_edit("Make it pop and feel premium").needs_agent


def test_overlay_text_is_whitelisted_no_shell_or_filter_metacharacters():
    assert clean_overlay_text("Shop now; rm -rf / `whoami` $(x) 'y' %{pts}") == "Shop now rm -rf  whoami x 'y' pts"
    assert clean_overlay_text("x" * 200) == "x" * 60
    assert clean_overlay_text("   ") is None
    p = plan_edit("Add a CTA", cta_text="50% off: today only!!! {x}")
    assert "%" not in p.cta_text and "{" not in p.cta_text


APP_CLEAN_INSTRUCTION = (
    "Clean this up. Remove retakes and mistakes, keep only the best take of each line, "
    "and remove dead air and awkward pauses."
)  # must equal EditIntent.cleanInstruction in mobile/lib/core/intents/edit_intent.dart


def test_the_apps_clean_instruction_picks_best_takes_and_removes_gaps_without_speeding_up_or_shortening():
    plan = plan_edit(APP_CLEAN_INSTRUCTION)
    assert plan.best_takes and plan.remove_silence
    assert plan.speed_all == 1.0 and not plan.speed_opening and not plan.shorten
    assert plan.target_duration_seconds is None and plan.trim_start_seconds == 0.0
    assert plan.deterministic_only and not plan.generative_prompts
