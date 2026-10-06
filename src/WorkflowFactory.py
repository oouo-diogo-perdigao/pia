from __future__ import annotations

import random

from .config import (
    ICE_COMFYUI_MODEL_LAYOUT,
    ICE_COMFYUI_CHECKPOINT,
    ICE_COMFYUI_UNET,
    ICE_COMFYUI_CLIP_L,
    ICE_COMFYUI_T5XXL,
    ICE_COMFYUI_VAE,
    ICE_IMAGE_STEPS,
    ICE_IMAGE_CFG,
    ICE_IMAGE_SAMPLER,
    ICE_IMAGE_SCHEDULER,
    ICE_IMAGE_FLUX_GUIDANCE,
    ICE_IMAGE_EDIT_GROW_MASK_BY,
)


class WorkflowConfigurationError(ValueError):
    pass


def _node(class_type: str, **inputs):
    return {"class_type": class_type, "inputs": inputs}


def _seed(seed: int | None) -> int:
    if seed is None:
        return random.SystemRandom().randint(0, 2**63 - 1)
    value = int(seed)
    return random.SystemRandom().randint(0, 2**63 - 1) if value < 0 else value


def _model_nodes():
    if ICE_COMFYUI_MODEL_LAYOUT == "checkpoint":
        nodes = {
            "10": _node("CheckpointLoaderSimple", ckpt_name=ICE_COMFYUI_CHECKPOINT)
        }
        return nodes, ["10", 0], ["10", 1], ["10", 2]

    if ICE_COMFYUI_MODEL_LAYOUT == "split":
        nodes = {
            "10": _node(
                "UNETLoader", unet_name=ICE_COMFYUI_UNET, weight_dtype="default"
            ),
            "11": _node(
                "DualCLIPLoader",
                clip_name1=ICE_COMFYUI_CLIP_L,
                clip_name2=ICE_COMFYUI_T5XXL,
                type="flux",
                device="default",
            ),
            "12": _node("VAELoader", vae_name=ICE_COMFYUI_VAE),
        }
        return nodes, ["10", 0], ["11", 0], ["12", 0]

    raise WorkflowConfigurationError(
        "COMFYUI_MODEL_LAYOUT deve ser 'checkpoint' ou 'split'."
    )


def _conditioning_nodes(prompt: str, clip_ref):
    if ICE_COMFYUI_MODEL_LAYOUT == "checkpoint":
        return (
            {
                "20": _node("CLIPTextEncode", text=prompt, clip=clip_ref),
                "21": _node("CLIPTextEncode", text="", clip=clip_ref),
            },
            ["20", 0],
            ["21", 0],
        )

    return (
        {
            "20": _node(
                "CLIPTextEncodeFlux",
                clip=clip_ref,
                clip_l=prompt,
                t5xxl=prompt,
                guidance=ICE_IMAGE_FLUX_GUIDANCE,
            ),
            "21": _node("ConditioningZeroOut", conditioning=["20", 0]),
        },
        ["20", 0],
        ["21", 0],
    )


def build_generation_workflow(
    *,
    prompt: str,
    width: int,
    height: int,
    n: int,
    seed: int | None = None,
    steps: int | None = None,
) -> dict:
    nodes, model_ref, clip_ref, vae_ref = _model_nodes()
    conditioning, positive_ref, negative_ref = _conditioning_nodes(prompt, clip_ref)
    nodes.update(conditioning)
    nodes.update(
        {
            "30": _node(
                "EmptySD3LatentImage", width=width, height=height, batch_size=n
            ),
            "40": _node(
                "KSampler",
                model=model_ref,
                seed=_seed(seed),
                steps=int(steps or ICE_IMAGE_STEPS),
                cfg=ICE_IMAGE_CFG,
                sampler_name=ICE_IMAGE_SAMPLER,
                scheduler=ICE_IMAGE_SCHEDULER,
                positive=positive_ref,
                negative=negative_ref,
                latent_image=["30", 0],
                denoise=1.0,
            ),
            "50": _node("VAEDecode", samples=["40", 0], vae=vae_ref),
            "60": _node(
                "SaveImage",
                images=["50", 0],
                filename_prefix="openai_gateway/generation",
            ),
        }
    )
    return nodes


def build_edit_workflow(
    *,
    prompt: str,
    image_name: str,
    mask_name: str | None,
    width: int,
    height: int,
    n: int,
    denoise: float,
    seed: int | None = None,
    steps: int | None = None,
) -> dict:
    nodes, model_ref, clip_ref, vae_ref = _model_nodes()
    conditioning, positive_ref, negative_ref = _conditioning_nodes(prompt, clip_ref)
    nodes.update(conditioning)

    nodes["30"] = _node("LoadImage", image=image_name)
    nodes["31"] = _node(
        "ImageScale",
        image=["30", 0],
        upscale_method="lanczos",
        width=width,
        height=height,
        crop="center",
    )

    if mask_name:
        nodes["32"] = _node("LoadImage", image=mask_name)
        nodes["33"] = _node(
            "VAEEncodeForInpaint",
            pixels=["31", 0],
            vae=vae_ref,
            mask=["32", 1],
            grow_mask_by=ICE_IMAGE_EDIT_GROW_MASK_BY,
        )
        latent_ref = ["33", 0]
    else:
        nodes["33"] = _node("VAEEncode", pixels=["31", 0], vae=vae_ref)
        latent_ref = ["33", 0]

    if n > 1:
        nodes["34"] = _node("RepeatLatentBatch", samples=latent_ref, amount=n)
        latent_ref = ["34", 0]

    nodes.update(
        {
            "40": _node(
                "KSampler",
                model=model_ref,
                seed=_seed(seed),
                steps=int(steps or ICE_IMAGE_STEPS),
                cfg=ICE_IMAGE_CFG,
                sampler_name=ICE_IMAGE_SAMPLER,
                scheduler=ICE_IMAGE_SCHEDULER,
                positive=positive_ref,
                negative=negative_ref,
                latent_image=latent_ref,
                denoise=float(denoise),
            ),
            "50": _node("VAEDecode", samples=["40", 0], vae=vae_ref),
            "60": _node(
                "SaveImage", images=["50", 0], filename_prefix="openai_gateway/edit"
            ),
        }
    )
    return nodes
