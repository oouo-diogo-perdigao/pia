import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Modal,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import {
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { api, safe } from "./api";
import { notify } from "./toasts";
import {
  SKILL_CATEGORIES,
  createEmptySkillDraft,
  draftToSkillPayload,
  filterSkills,
  normalizeSkills,
  skillToDraft,
  validateSkillDraft,
} from "./extensions-helpers";

const SKILL_ACTION_TYPES = [
  { value: "command", label: "Comando local / executável" },
  { value: "prompt", label: "Instrução / prompt reutilizável" },
  { value: "tool", label: "Ferramenta interna da PIA" },
];

export default function SkillsPanel() {
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState("");
  const [draft, setDraft] = useState(() => createEmptySkillDraft());
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState("");
  const [executionResult, setExecutionResult] = useState(null);

  async function loadSkills() {
    setLoading(true);
    try {
      const response = await api("/skills");
      setSkills(normalizeSkills(response));
    } catch {
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSkills();
  }, []);

  const visible = useMemo(
    () => filterSkills(skills, { category, query }),
    [skills, category, query],
  );

  function openNewModal() {
    setEditingId("");
    setDraft(createEmptySkillDraft());
    setEditorOpen(true);
  }

  function openEditModal(skill) {
    setEditingId(skill.id);
    setDraft(skillToDraft(skill));
    setEditorOpen(true);
  }

  async function handleSave() {
    const check = validateSkillDraft(draft);
    if (!check.valid) {
      notify(check.errors[0]);
      return;
    }
    setSaving(true);
    try {
      const payload = draftToSkillPayload(draft);
      if (editingId) {
        await api(`/skills/${encodeURIComponent(editingId)}`, payload, {
          method: "PUT",
        });
      } else {
        await api("/skills", payload, { method: "POST" });
      }
      setEditorOpen(false);
      await loadSkills();
      notify("Skill salva.");
    } finally {
      setSaving(false);
    }
  }

  async function handleToggle(skill) {
    const nextEnabled = !skill.enabled;
    await api(`/skills/${encodeURIComponent(skill.id)}/toggle`, {
      enabled: nextEnabled,
    });
    await loadSkills();
    notify(`Skill "${skill.name}" ${nextEnabled ? "ativada" : "desativada"}.`);
  }

  async function handleDelete(skill) {
    if (!confirm(`Excluir a skill "${skill.name}"?`)) return;
    await api(
      `/skills/${encodeURIComponent(skill.id)}`,
      {},
      { method: "DELETE" },
    );
    await loadSkills();
    notify("Skill excluída.");
  }

  async function handleExecute(skill) {
    setRunningId(skill.id);
    try {
      const result = await api(
        `/skills/${encodeURIComponent(skill.id)}/execute`,
        {},
      );
      setExecutionResult({ skill, result });
      notify(`Skill "${skill.name}" executada.`);
    } finally {
      setRunningId("");
    }
  }

  return (
    <div className="panel">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <div>
          <Text size="xl" fw={700}>
            Skills da PIA
          </Text>
          <Text size="sm" c="dimmed">
            Habilidades executáveis nativas e personalizadas (ex.: iniciar
            aplicativos do Windows, capturar tela, automatizar rotinas rápidas).
          </Text>
        </div>
        <Group gap="xs">
          <Button
            variant="light"
            color="gray"
            leftSection={<RefreshCw size={15} />}
            onClick={safe(loadSkills)}
            loading={loading}
          >
            Atualizar
          </Button>
          <Button leftSection={<Plus size={16} />} onClick={openNewModal}>
            Nova Skill
          </Button>
        </Group>
      </Group>

      <Group gap="sm" align="center" wrap="wrap">
        <TextInput
          placeholder="Buscar skill por nome, gatilho ou comando…"
          leftSection={<Search size={15} />}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          style={{ flex: 1, minWidth: 240 }}
        />
        <SegmentedControl
          size="xs"
          value={category}
          onChange={setCategory}
          data={SKILL_CATEGORIES}
        />
      </Group>

      {executionResult && (
        <Alert
          color="teal"
          title={`Resultado de execução · ${executionResult.skill.name}`}
          withCloseButton
          onClose={() => setExecutionResult(null)}
        >
          <Code block>
            {typeof executionResult.result === "string"
              ? executionResult.result
              : JSON.stringify(executionResult.result, null, 2)}
          </Code>
        </Alert>
      )}

      {loading && skills.length === 0 ? (
        <Text c="dimmed">Carregando skills…</Text>
      ) : visible.length === 0 ? (
        <Paper p="xl" radius="md" withBorder>
          <Stack align="center" gap="xs">
            <Sparkles size={26} />
            <Text fw={600}>Nenhuma skill encontrada</Text>
            <Text size="sm" c="dimmed">
              Crie uma skill personalizada ou altere o filtro de categoria.
            </Text>
          </Stack>
        </Paper>
      ) : (
        <Stack gap="sm">
          {visible.map((skill) => (
            <Paper
              key={skill.id}
              p="md"
              radius="md"
              withBorder
              className="extension-card"
            >
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={6} style={{ flex: 1, minWidth: 260 }}>
                  <Group gap="xs" wrap="wrap">
                    <Text fw={600} size="md">
                      {skill.name}
                    </Text>
                    <Badge
                      size="sm"
                      variant="light"
                      color={skill.native ? "blue" : "violet"}
                    >
                      {skill.native ? "Nativa" : "Personalizada"}
                    </Badge>
                    <Badge size="sm" variant="light" color="gray">
                      {skill.category}
                    </Badge>
                    <Badge
                      size="sm"
                      variant="dot"
                      color={skill.enabled ? "green" : "gray"}
                    >
                      {skill.enabled ? "Ativa" : "Inativa"}
                    </Badge>
                  </Group>

                  {skill.description && (
                    <Text size="sm" c="dimmed">
                      {skill.description}
                    </Text>
                  )}

                  {(skill.trigger || skill.command) && (
                    <Group gap="xs" wrap="wrap">
                      {skill.trigger && <Code>Gatilho: {skill.trigger}</Code>}
                      {skill.command && <Code>{skill.command}</Code>}
                    </Group>
                  )}
                </Stack>

                <Group gap="xs" align="center">
                  <Button
                    size="xs"
                    variant="light"
                    color="teal"
                    leftSection={<Play size={13} />}
                    loading={runningId === skill.id}
                    onClick={safe(() => handleExecute(skill))}
                  >
                    Executar
                  </Button>
                  {!skill.native && (
                    <>
                      <Button
                        size="xs"
                        variant="default"
                        leftSection={<Pencil size={13} />}
                        onClick={() => openEditModal(skill)}
                      >
                        Editar
                      </Button>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={`Excluir ${skill.name}`}
                        onClick={safe(() => handleDelete(skill))}
                      >
                        <Trash2 size={15} />
                      </ActionIcon>
                    </>
                  )}
                  <Switch
                    checked={skill.enabled}
                    onChange={safe(() => handleToggle(skill))}
                    aria-label={`Alternar skill ${skill.name}`}
                  />
                </Group>
              </Group>
            </Paper>
          ))}
        </Stack>
      )}

      <Modal
        opened={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={editingId ? "Editar Skill" : "Nova Skill Personalizada"}
        size="md"
      >
        <Stack gap="sm">
          <TextInput
            label="Nome"
            placeholder="Ex.: Abrir VS Code no projeto PIA"
            value={draft.name}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                name: event.currentTarget.value,
              }))
            }
          />
          <Textarea
            label="Descrição"
            placeholder="Descreva quando a PIA deve usar esta skill"
            minRows={2}
            value={draft.description}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                description: event.currentTarget.value,
              }))
            }
          />
          <Group grow>
            <Select
              label="Categoria"
              data={SKILL_CATEGORIES.filter((c) => c.value !== "all")}
              value={draft.category}
              onChange={(value) =>
                setDraft((prev) => ({
                  ...prev,
                  category: value || "custom",
                }))
              }
            />
            <Select
              label="Tipo de ação"
              data={SKILL_ACTION_TYPES}
              value={draft.action_type}
              onChange={(value) =>
                setDraft((prev) => ({
                  ...prev,
                  action_type: value || "command",
                }))
              }
            />
          </Group>
          <TextInput
            label="Gatilho / palavra-chave (opcional)"
            placeholder="Ex.: abrir notepad, screenshot"
            value={draft.trigger}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                trigger: event.currentTarget.value,
              }))
            }
          />
          <TextInput
            label="Comando executável (opcional)"
            placeholder="Ex.: notepad.exe"
            value={draft.command}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                command: event.currentTarget.value,
              }))
            }
          />
          <Textarea
            label="Instruções para o modelo (opcional)"
            placeholder="Passos ou contexto extra que a skill fornece ao assistente"
            minRows={3}
            value={draft.instructions}
            onChange={(event) =>
              setDraft((prev) => ({
                ...prev,
                instructions: event.currentTarget.value,
              }))
            }
          />
          <Group justify="flex-end" mt="xs">
            <Button
              variant="subtle"
              color="gray"
              onClick={() => setEditorOpen(false)}
            >
              Cancelar
            </Button>
            <Button onClick={safe(handleSave)} loading={saving}>
              Salvar Skill
            </Button>
          </Group>
        </Stack>
      </Modal>
    </div>
  );
}
