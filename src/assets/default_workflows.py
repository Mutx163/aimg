
DEFAULT_T2I_WORKFLOW = {
  "3": {
    "inputs": {
      "seed": 156680208700286,
      "steps": 9,
      "cfg": 1.0,
      "sampler_name": "euler",
      "scheduler": "simple",
      "denoise": 1.0,
      "model": ["11", 0],
      "positive": ["6", 0],
      "negative": ["7", 0],
      "latent_image": ["5", 0]
    },
    "class_type": "KSampler",
    "_meta": {"title": "KSampler"}
  },
  "5": {
    "inputs": {
      "width": 1200,
      "height": 1600,
      "batch_size": 1
    },
    "class_type": "EmptyLatentImage",
    "_meta": {"title": "Empty Latent Image"}
  },
  "6": {
    "inputs": {
      "text": "beautiful scenery",
      "clip": ["18", 0]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "CLIP Text Encode (Prompt)"}
  },
  "7": {
    "inputs": {
      "text": "blurry, low quality",
      "clip": ["18", 0]
    },
    "class_type": "CLIPTextEncode",
    "_meta": {"title": "CLIP Text Encode (Negative)"}
  },
  "8": {
    "inputs": {
      "samples": ["3", 0],
      "vae": ["17", 0]
    },
    "class_type": "VAEDecode",
    "_meta": {"title": "VAE Decode"}
  },
  "9": {
    "inputs": {
      "filename_prefix": "ComfyUI",
      "images": ["8", 0]
    },
    "class_type": "SaveImage",
    "_meta": {"title": "Save Image"}
  },
  "11": {
    "inputs": {
      "model": ["28", 0],
      "shift": 3.0
    },
    "class_type": "ModelSamplingAuraFlow",
    "_meta": {"title": "ModelSamplingAuraFlow"}
  },
  "16": {
    "inputs": {
      "unet_name": "z_image_turbo_bf16.safetensors",
      "weight_dtype": "default"
    },
    "class_type": "UNETLoader",
    "_meta": {"title": "Load UNET"}
  },
  "17": {
    "inputs": {
      "vae_name": "ae.safetensors"
    },
    "class_type": "VAELoader",
    "_meta": {"title": "Load VAE"}
  },
  "18": {
    "inputs": {
      "clip_name": "qwen_3_4b.safetensors",
      "type": "qwen_image",
      "device": "default"
    },
    "class_type": "CLIPLoader",
    "_meta": {"title": "Load CLIP"}
  },
  "28": {
    "inputs": {
      "model": ["16", 0],
      "lora_name": "yyyy_000002250.safetensors",
      "strength_model": 0.0
    },
    "class_type": "LoraLoaderModelOnly",
    "_meta": {"title": "Load LoRA (Model Only)"}
  }
}
