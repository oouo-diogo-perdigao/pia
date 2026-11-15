"""Skills catalog routes for /api/pia/skills/*."""

from __future__ import annotations

from src.integrations.skills import get_skills_catalog


def _list_skills(ctx, data, query):
    return {"skills": get_skills_catalog().list_skills()}


def _create_skill(ctx, data, query):
    return {"skill": get_skills_catalog().create_skill(data)}


def _get_skill(ctx, data, query, skill_id):
    return {"skill": get_skills_catalog().get_skill(skill_id)}


def _update_skill(ctx, data, query, skill_id):
    return {"skill": get_skills_catalog().update_skill(skill_id, data)}


def _delete_skill(ctx, data, query, skill_id):
    return get_skills_catalog().delete_skill(skill_id)


def _toggle_skill(ctx, data, query, skill_id):
    return {
        "skill": get_skills_catalog().toggle_skill(
            skill_id, data.get("enabled") if "enabled" in data else None
        )
    }


def _execute_skill(ctx, data, query, skill_id):
    return get_skills_catalog().execute_skill(skill_id, data)


def register(router) -> None:
    router.add("GET", "/skills", _list_skills, description="Listar skills")
    router.add(
        "POST", "/skills", _create_skill, description="Criar skill personalizada"
    )
    router.add("GET", "/skills/{skill_id}", _get_skill, description="Obter skill")
    router.add(
        "PUT", "/skills/{skill_id}", _update_skill, description="Atualizar skill"
    )
    router.add(
        "POST", "/skills/{skill_id}", _update_skill, description="Atualizar skill"
    )
    router.add(
        "PATCH", "/skills/{skill_id}", _update_skill, description="Atualizar skill"
    )
    router.add(
        "DELETE", "/skills/{skill_id}", _delete_skill, description="Excluir skill"
    )
    router.add(
        "POST",
        "/skills/{skill_id}/toggle",
        _toggle_skill,
        description="Ativar/desativar skill",
    )
    router.add(
        "POST",
        "/skills/{skill_id}/execute",
        _execute_skill,
        description="Executar skill",
    )
