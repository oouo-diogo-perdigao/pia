import React, { useState } from "react";
import {
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { Check, KeyRound, Plug } from "lucide-react";
import { api, safe } from "./api";
import { usePia } from "./shared";
import {
  ICE_SIZE_OPTIONS,
  LLM_MODEL_OPTIONS,
  STT_LANG_OPTIONS,
  STT_MODEL_OPTIONS,
  fromSttLangSelectValue,
  isRecordingSoundsEnabled,
  mergeSelectOptions,
  toSttLangSelectValue,
  toggleRecordingSounds,
} from "./settings-simplification";

function fieldByName(fields, name) {
  return fields.find((f) => (f.base || f.name) === name) || null;
}

function VaultLinkRow({ title, description, configured, onOpenVault }) {
  return (
    <div className="settings-row">
      <div className="settings-row-info">
        <Group gap="xs">
          <Text size="sm" fw={600}>
            {title}
          </Text>
          <Badge
            size="xs"
            variant="light"
            color={configured ? "teal" : "yellow"}
          >
            {configured ? "Configurada" : "Não configurada"}
          </Badge>
        </Group>
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      </div>
      <div className="settings-row-control">
        <Button
          size="xs"
          variant="light"
          leftSection={<KeyRound size={14} />}
          onClick={onOpenVault}
        >
          Configurar no Cofre
        </Button>
      </div>
    </div>
  );
}

export default function GeneralSettingsTabs({
  group,
  fields,
  values,
  initialValues,
  setValues,
}) {
  const { language, setLanguage, navigate } = usePia();
  const [editingIceUrl, setEditingIceUrl] = useState(false);

  const openVault = () =>
    navigate({ view: "settings", section: "credentials" });

  if (group === "Geral") {
    const compatKey = fieldByName(fields, "OPENAI_COMPAT_API_KEY");
    return (
      <Stack gap="lg">
        <div>
          <div className="settings-section-title">Preferências</div>
          <div className="settings-card">
            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Idioma da interface
                </Text>
                <Text size="xs" c="dimmed">
                  Define o idioma exibido nos menus e telas da PIA.
                </Text>
              </div>
              <div className="settings-row-control">
                <Select
                  w={220}
                  aria-label="Idioma da interface"
                  value={language}
                  data={[
                    { value: "pt-BR", label: "Português (Brasil)" },
                    { value: "en", label: "English" },
                  ]}
                  onChange={safe(async (value) => {
                    if (!value || value === language) return;
                    await api("/preferences", { language: value });
                    setLanguage(value);
                  })}
                />
              </div>
            </div>
          </div>
        </div>

        <div>
          <div className="settings-section-title">Servidor compatível</div>
          <div className="settings-card">
            <VaultLinkRow
              title="Servidor compatível com OpenAI"
              description="Chave de acesso para aplicativos externos se conectarem à PIA localmente."
              configured={Boolean(compatKey?.configured)}
              onOpenVault={openVault}
            />
          </div>
        </div>
      </Stack>
    );
  }

  if (group === "STT") {
    const sttGeminiKey = fieldByName(fields, "STT_GEMINI_API_KEY");
    const sttModelValue = values.STT_MODEL ?? "large-v3-turbo";
    const sttLangSelectValue = toSttLangSelectValue(values.STT_LANG);
    return (
      <Stack gap="lg">
        <div>
          <div className="settings-section-title">Ditado</div>
          <div className="settings-card">
            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Modelo
                </Text>
                <Text size="xs" c="dimmed">
                  Transcreve a sua fala em cerca de 100 idiomas neste
                  computador.
                </Text>
              </div>
              <div className="settings-row-control">
                <Select
                  w={280}
                  aria-label="Modelo de ditado"
                  data={mergeSelectOptions(STT_MODEL_OPTIONS, sttModelValue)}
                  value={sttModelValue}
                  onChange={(val) =>
                    val && setValues((old) => ({ ...old, STT_MODEL: val }))
                  }
                />
              </div>
            </div>

            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Idioma
                </Text>
                <Text size="xs" c="dimmed">
                  O idioma que você fala. Automático o detecta a partir da
                  gravação.
                </Text>
              </div>
              <div className="settings-row-control">
                <Select
                  w={280}
                  aria-label="Idioma do ditado"
                  data={mergeSelectOptions(
                    STT_LANG_OPTIONS,
                    sttLangSelectValue,
                  )}
                  value={sttLangSelectValue}
                  onChange={(val) =>
                    setValues((old) => ({
                      ...old,
                      STT_LANG: fromSttLangSelectValue(val),
                    }))
                  }
                />
              </div>
            </div>
          </div>
        </div>

        <div>
          <div className="settings-section-title">Transcrição na nuvem</div>
          <div className="settings-card">
            <VaultLinkRow
              title="Chaves de transcrição remota"
              description="Credenciais opcionais do Gemini e Groq são gerenciadas no Cofre."
              configured={Boolean(sttGeminiKey?.configured)}
              onOpenVault={openVault}
            />
          </div>
        </div>
      </Stack>
    );
  }

  if (group === "Imagens · ICE") {
    const comfyUrl = String(values.ICE_COMFYUI_URL || "").trim();
    const defaultSize = values.ICE_IMAGE_DEFAULT_SIZE ?? "1024x1024";
    return (
      <Stack gap="lg">
        <div>
          <div className="settings-section-title">Geração de imagens</div>
          <div className="settings-card">
            <div className="settings-row">
              <div className="settings-row-info">
                <Group gap="xs">
                  <Text size="sm" fw={600}>
                    Servidor de geração de imagens
                  </Text>
                  <Badge
                    size="xs"
                    variant="light"
                    color={comfyUrl ? "teal" : "gray"}
                    leftSection={<Plug size={11} />}
                  >
                    {comfyUrl ? "Configurado" : "Não configurado"}
                  </Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  {comfyUrl
                    ? `Conectado em ${comfyUrl}`
                    : "Informe o endereço local do ComfyUI para gerar imagens."}
                </Text>
              </div>
              <div className="settings-row-control">
                {editingIceUrl ? (
                  <Group gap="xs">
                    <TextInput
                      w={240}
                      aria-label="Endereço do servidor de imagens"
                      placeholder="http://127.0.0.1:8188"
                      value={values.ICE_COMFYUI_URL ?? ""}
                      onChange={(e) => {
                        const next = e.currentTarget.value;
                        setValues((old) => ({ ...old, ICE_COMFYUI_URL: next }));
                      }}
                    />
                    <Button
                      size="xs"
                      variant="light"
                      leftSection={<Check size={14} />}
                      onClick={() => setEditingIceUrl(false)}
                    >
                      OK
                    </Button>
                  </Group>
                ) : (
                  <Button
                    size="xs"
                    variant="light"
                    onClick={() => setEditingIceUrl(true)}
                  >
                    {comfyUrl ? "Alterar endereço" : "Configurar"}
                  </Button>
                )}
              </div>
            </div>

            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Tamanho padrão
                </Text>
                <Text size="xs" c="dimmed">
                  Resolução usada quando nenhum tamanho específico for pedido.
                </Text>
              </div>
              <div className="settings-row-control">
                <Select
                  w={240}
                  aria-label="Tamanho padrão das imagens"
                  data={mergeSelectOptions(ICE_SIZE_OPTIONS, defaultSize)}
                  value={defaultSize}
                  onChange={(val) =>
                    val &&
                    setValues((old) => ({
                      ...old,
                      ICE_IMAGE_DEFAULT_SIZE: val,
                    }))
                  }
                />
              </div>
            </div>
          </div>
        </div>
      </Stack>
    );
  }

  if (group === "LLMs") {
    const modelValue = values.LLM_MODEL ?? "free";
    const remoteKeys = [
      fieldByName(fields, "AGE_GEMINI_API_KEY"),
      fieldByName(fields, "GROQ_API_KEY"),
      fieldByName(fields, "OPENROUTER_API_KEY"),
      fieldByName(fields, "CLOUDFLARE_API_TOKEN"),
      fieldByName(fields, "CLOUDFLARE_API_KEY"),
    ].filter(Boolean);
    const anyConfigured = remoteKeys.some((item) => item.configured);

    return (
      <Stack gap="lg">
        <div>
          <div className="settings-section-title">Assistente e modelos</div>
          <div className="settings-card">
            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Como a PIA deve te chamar
                </Text>
                <Text size="xs" c="dimmed">
                  Nome ou apelido usado nas respostas da assistente.
                </Text>
              </div>
              <div className="settings-row-control">
                <TextInput
                  w={240}
                  aria-label="Como a PIA deve te chamar"
                  value={values.AGE_USER_NAME ?? ""}
                  onChange={(e) => {
                    const next = e.currentTarget.value;
                    setValues((old) => ({ ...old, AGE_USER_NAME: next }));
                  }}
                />
              </div>
            </div>

            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Modelo padrão
                </Text>
                <Text size="xs" c="dimmed">
                  Equilibra velocidade, qualidade e custo nas conversas.
                </Text>
              </div>
              <div className="settings-row-control">
                <Select
                  w={260}
                  aria-label="Modelo padrão de LLM"
                  data={mergeSelectOptions(LLM_MODEL_OPTIONS, modelValue)}
                  value={modelValue}
                  onChange={(val) =>
                    val && setValues((old) => ({ ...old, LLM_MODEL: val }))
                  }
                />
              </div>
            </div>

            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Modelo local (Ollama)
                </Text>
                <Text size="xs" c="dimmed">
                  Usado offline ou quando nenhum provedor remoto estiver ativo.
                </Text>
              </div>
              <div className="settings-row-control">
                <TextInput
                  w={260}
                  aria-label="Modelo local (Ollama)"
                  placeholder="ollama/qwen3:8b"
                  value={values.LLM_LOCAL_MODEL ?? ""}
                  onChange={(e) => {
                    const next = e.currentTarget.value;
                    setValues((old) => ({ ...old, LLM_LOCAL_MODEL: next }));
                  }}
                />
              </div>
            </div>
          </div>
        </div>

        <div>
          <div className="settings-section-title">Chaves de API</div>
          <div className="settings-card">
            <VaultLinkRow
              title="Provedores na nuvem (Gemini, Groq, OpenRouter, Cloudflare)"
              description="Todas as chaves de API ficam centralizadas com segurança no Cofre."
              configured={anyConfigured}
              onOpenVault={openVault}
            />
          </div>
        </div>
      </Stack>
    );
  }

  if (group === "Voz e áudio") {
    const soundsEnabled = isRecordingSoundsEnabled(values);
    return (
      <Stack gap="lg">
        <div>
          <div className="settings-section-title">Sinais sonoros</div>
          <div className="settings-card">
            <div className="settings-row">
              <div className="settings-row-info">
                <Text size="sm" fw={600}>
                  Tocar sons ao iniciar e encerrar gravação
                </Text>
                <Text size="xs" c="dimmed">
                  Emite um aviso sonoro curto quando o microfone ativa e quando
                  a fala termina.
                </Text>
              </div>
              <div className="settings-row-control">
                <Switch
                  aria-label="Tocar sons ao iniciar e encerrar gravação"
                  checked={soundsEnabled}
                  onChange={(e) => {
                    const next = e.currentTarget.checked;
                    setValues((old) =>
                      toggleRecordingSounds(old, next, initialValues),
                    );
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </Stack>
    );
  }

  return null;
}
