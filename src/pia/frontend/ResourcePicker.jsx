import React, { useEffect, useState } from "react";
import {
  Modal,
  Stack,
  Select,
  Group,
  Button,
  Text,
  Loader,
} from "@mantine/core";
import { ChevronRight, ChevronDown, Folder, Database } from "lucide-react";
import { api, appApi, report, safe } from "./api";

function FolderNode({ node, account, selected, onSelect, parentPath = "" }) {
  const path = parentPath ? parentPath + " / " + node.name : node.name;
  const [open, setOpen] = useState(false),
    [children, setChildren] = useState(null),
    [cursor, setCursor] = useState(null),
    [busy, setBusy] = useState(false);
  async function load(more = false) {
    setBusy(true);
    try {
      const result = await api("/integrations/google/folders", {
        account,
        folder: node.id,
        cursor: more ? cursor : null,
      });
      setChildren((old) => (more ? [...old, ...result.files] : result.files));
      setCursor(result.nextPageToken || null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="folder-node">
      <Group gap={3} wrap="nowrap">
        <Button
          variant="subtle"
          size="compact-xs"
          aria-label={"Expandir " + node.name}
          onClick={safe(async () => {
            setOpen(!open);
            if (!open && !children) await load();
          })}
        >
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </Button>
        <Button
          fullWidth
          justify="start"
          variant={selected?.id === node.id ? "light" : "subtle"}
          leftSection={<Folder size={17} />}
          onClick={() => onSelect({ ...node, path })}
        >
          {node.name}
        </Button>
      </Group>
      {open && (
        <div
          style={{
            marginLeft: 20,
            borderLeft: "1px solid #37334f",
            paddingLeft: 5,
          }}
        >
          {busy && <Loader size="xs" />}
          {children?.map((child) => (
            <FolderNode
              key={child.id}
              node={child}
              parentPath={path}
              account={account}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
          {children?.length === 0 && (
            <Text size="xs" c="dimmed">
              Sem subpastas
            </Text>
          )}
          {cursor && (
            <Button variant="subtle" onClick={safe(() => load(true))}>
              Carregar mais
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
export default function ResourcePicker({
  kind,
  accounts,
  initialAccount,
  onClose,
  onChoose,
}) {
  const [account, setAccount] = useState(
      initialAccount || accounts[0]?.id || null,
    ),
    [items, setItems] = useState([]),
    [selected, setSelected] = useState(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setItems([]);
    setSelected(null);
    if (!account) return;
    if (kind === "google") {
      setItems([{ id: "root", name: "Meu Drive" }]);
      return;
    }
    setBusy(true);
    appApi("object_storage", "buckets", { account })
      .then((result) => {
        if (active)
          setItems(result.buckets.map((name) => ({ id: name, name })));
      })
      .catch(report)
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [account, kind]);
  return (
    <Modal
      opened
      onClose={onClose}
      size="lg"
      title={
        kind === "google"
          ? "Escolher pasta de gravações"
          : "Escolher bucket de destino"
      }
    >
      <Stack>
        <Select
          label="Conta"
          data={accounts.map((a) => ({
            value: a.id,
            label: a.label || a.name || a.email,
          }))}
          value={account}
          onChange={setAccount}
        />
        <div
          style={{ minHeight: 200, maxHeight: "50vh", overflow: "auto" }}
          key={account}
        >
          {busy && <Loader />}
          {kind === "google"
            ? items.map((node) => (
                <FolderNode
                  key={node.id}
                  node={node}
                  account={account}
                  selected={selected}
                  onSelect={setSelected}
                />
              ))
            : items.map((node) => (
                <Button
                  key={node.id}
                  fullWidth
                  justify="start"
                  variant={selected?.id === node.id ? "light" : "subtle"}
                  leftSection={<Database size={17} />}
                  onClick={() => setSelected(node)}
                >
                  {node.name}
                </Button>
              ))}
          {!account && <Text>Conecte uma conta para continuar.</Text>}
        </div>
        <Text size="sm">
          {selected
            ? "Selecionado: " + selected.name
            : "Expanda as pastas e escolha o destino."}
        </Text>
        <Button
          disabled={!selected}
          onClick={() => onChoose({ account, ...selected })}
        >
          Usar {kind === "google" ? "esta pasta" : "este bucket"}
        </Button>
      </Stack>
    </Modal>
  );
}
