import sys
import json
import torch
import argparse
from transformers import pipeline

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt_file", required=True)
    parser.add_argument("--output_file", required=True)
    args = parser.parse_args()

    with open(args.prompt_file, "r") as f:
        prompt = f.read()

    # Load a small, fast model available on the cluster
    model_id = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    try:
        pipe = pipeline("text-generation", model=model_id, device=0, torch_dtype=torch.float16)
        
        # Format the prompt slightly
        system_msg = "You are a scientific research assistant. Extract metadata from the paper and output ONLY valid JSON."
        full_prompt = f"{system_msg}\n\n{prompt}"

        output = pipe(full_prompt, max_new_tokens=256, do_sample=False, return_full_text=False)
        response_text = output[0]['generated_text']

        with open(args.output_file, "w") as f:
            f.write(response_text)
            
    except Exception as e:
        with open(args.output_file, "w") as f:
            f.write(f"ERROR: {str(e)}")

if __name__ == "__main__":
    main()
