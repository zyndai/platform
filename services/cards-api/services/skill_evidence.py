"""Attach public source links from actual imported evidence, never invented URLs."""
from models.card import CardSynthesis, SkillEvidence, normalize_booking_url


def attach_evidence(synth: CardSynthesis, github: dict | None) -> None:
    from services.search_constraints import skill_matches
    repos = (github or {}).get("repos") or []
    for skill in synth.skills:
        evidence = list(skill.evidence)
        seen = {e.url for e in evidence}
        for repo in repos:
            url = normalize_booking_url(repo.get("html_url"))
            if not url or repo.get("fork") or not repo.get("language") or not skill_matches(skill.name, repo["language"]):
                continue
            if url not in seen and len(evidence) < 5:
                evidence.append(SkillEvidence(label=repo.get("full_name") or repo.get("name") or "Repository", url=url, kind="repository"))
                seen.add(url)
        skill.evidence = evidence
        skill.evidence_count = max(skill.evidence_count, len(evidence))
    for project in synth.projects:
        for repo in repos:
            if project.url.rstrip("/") != str(repo.get("html_url") or "").rstrip("/"):
                continue
            project.stars = repo.get("stargazers_count")
            project.demo_url = normalize_booking_url(repo.get("homepage"))
            break
