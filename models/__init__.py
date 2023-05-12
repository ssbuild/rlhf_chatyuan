# -*- coding: utf-8 -*-
# @Time:  11:30
# @Author: tk
from dataclasses import dataclass
from typing import List, Tuple, Optional, Union
import torch
from deep_training.data_helper import ModelArguments, TrainingArguments, DataArguments
from deep_training.nlp.rl.ppo.configuration import PPOArguments, PPOConfig
from deep_training.nlp.rl.ppo.ppo_module import PPOModelLoss, CausalLMOutputWithValue
from deep_training.nlp.utils import configure_optimizers
from torch import nn
from deep_training.nlp.models.lora.v2 import LoraModel, LoraArguments,LoraConfig
from deep_training.nlp.models.transformer import TransformerForSeq2SeqLM
from torch.optim import AdamW
from transformers import PreTrainedModel, HfArgumentParser, AutoConfig
from transformers.utils import ModelOutput
from config import reward_config
from deep_training.nlp.models.rl.modeling import AutoModelForSeq2SeqLMWithValueHead

#如果显卡支持int8 可以开启 ， 需安装依赖 pip install bitsandbytes
load_in_8bit = False


class Generate:
    @classmethod
    @torch.no_grad()
    def generate(cls,model, tokenizer, query: str, max_length: int = 2048, num_beams=1,
             do_sample=True, top_p=0.7, temperature=0.95, logits_processor=None, **kwargs):
        gen_kwargs = {"max_length": max_length, "num_beams": num_beams, "do_sample": do_sample, "top_p": top_p,
                      "temperature": temperature, "logits_processor": logits_processor, **kwargs}

        # prompt = "Human：" + query + "\nAssistant："
        #自行加模板
        prompt = query
        inputs = tokenizer([prompt], return_tensors="pt")
        inputs = inputs.to(model.device)
        outputs = model.generate(**inputs, **gen_kwargs)
        outputs = outputs.tolist()[0][len(inputs["input_ids"][0]):]
        response = tokenizer.decode(outputs)
        return response

    @classmethod
    @torch.no_grad()
    def chat(cls,model, tokenizer, query: str, history: List[Tuple[str, str]] = None, max_length: int = 2048, num_beams=1,
             do_sample=True, top_p=0.7, temperature=0.95, logits_processor=None, **kwargs):
        if history is None:
            history = []

        gen_kwargs = {"max_length": max_length, "num_beams": num_beams, "do_sample": do_sample, "top_p": top_p,
                      "temperature": temperature, "logits_processor": logits_processor, **kwargs}
        if not history:
            prompt = query
        else:
            prompt = ""
            for i, (old_query, response) in enumerate(history):
                prompt += "[Round {}]\n问：{}\n答：{}\n".format(i, old_query, response)
            prompt += "[Round {}]\n问：{}\n答：".format(len(history), query)
        inputs = tokenizer([prompt], return_tensors="pt")
        inputs = inputs.to(model.device)
        outputs = model.generate(**inputs, **gen_kwargs)
        outputs = outputs.tolist()[0][len(inputs["input_ids"][0]):]
        response = tokenizer.decode(outputs)
        history = history + [(query, response)]
        return response, history


class MyRewardModel(TransformerForSeq2SeqLM):
    def __init__(self, *args, **kwargs):
        if load_in_8bit:
            kwargs.update({"load_in_8bit": True, "device_map": "auto"})
        super(MyRewardModel, self).__init__(*args, **kwargs)
        self.score = nn.Linear(self.config.hidden_size, self.config.num_labels)
        if load_in_8bit:
            self.model.enable_input_require_grads()

    def forward_reward(self,**batch):
        back_module = self.model.lm_head
        self.model.lm_head = self.score
        state = self(**batch)[0]
        value = state
        self.model.lm_head = back_module
        return value.squeeze(-1)


    def forward_loss(self,chosen_ids: torch.Tensor, chosen_values: torch.Tensor,
                     rejected_ids: torch.Tensor, rejected_values: torch.Tensor):
        chosen_mean_scores = []
        rejected_mean_scores = []
        loss = 0.

        for i in range(chosen_ids.size(0)):
            chosen_id = chosen_ids[i]
            rejected_id = rejected_ids[i]
            chosen_value = chosen_values[i]
            rejected_value = rejected_values[i]

            # Check if there is any padding otherwise take length of sequence
            c_inds = (chosen_id == self.config.eos_token_id).nonzero()
            c_ind = c_inds[0].item() if len(c_inds) > 0 else chosen_id.shape[0]
            r_inds = (rejected_id == self.config.eos_token_id).nonzero()
            r_ind = r_inds[0].item() if len(r_inds) > 0 else rejected_id.shape[0]
            end_ind = max(c_ind, r_ind)

            # Retrieve first index where trajectories diverge
            divergence_ind = (chosen_id != rejected_id).nonzero()[0]
            assert divergence_ind > 0

            # Index into the correct rewards
            c_truncated_reward = chosen_value[divergence_ind:end_ind]
            r_truncated_reward = rejected_value[divergence_ind:end_ind]

            # Append the last rewards to the list of end scores
            chosen_mean_scores.append(c_truncated_reward[-1])
            rejected_mean_scores.append(r_truncated_reward[-1])

            # Compute loss based on truncated rewards (ignore padding)
            loss += -torch.log(torch.sigmoid(c_truncated_reward - r_truncated_reward)).mean()

        loss = loss / chosen_ids.size(0)
        chosen_mean_scores = torch.stack(chosen_mean_scores)
        rejected_mean_scores = torch.stack(rejected_mean_scores)
        return loss,chosen_mean_scores,rejected_mean_scores

    def forward_value(self,input_ids,values):
        bs = values.size(0)
        seq_len = input_ids.shape[1]
        chosen_mean_scores = [
        ]  # we use this name for consistency with the original forwad function
        for i in range(bs):
            input_id = input_ids[i]
            value = values[i]
            c_inds = (input_id == self.config.pad_token_id).nonzero()
            # here we only use the answer part of the sequence so we do not need to care about the padding at the beginning
            c_ind = c_inds[0].item() if len(c_inds) > 0 else seq_len
            chosen_mean_scores.append(value[c_ind - 1])
        return values,torch.stack(chosen_mean_scores)

    def forward_returns(self, **inputs):
        input_ids = inputs['decoder_input_ids']
        rewards = self.forward_reward(**inputs)
        ends = torch.argmax((input_ids == self.config.eos_token_id).float(), dim=1).view(-1, 1)
        returns = torch.gather(rewards, 1, ends).squeeze(-1)
        return returns

    def compute_loss(self, *args, return_value_only=False, **batch) -> tuple:
        input_a, input_b = {}, {}
        for k, v in batch.items():
            i, k = (input_b, k[:-1]) if k.endswith('2') else (input_a, k)
            i[k] = v

        value_a = self.forward_reward(**input_a)
        if len(input_b) > 0:
            value_b = self.forward_reward(**input_b)
            loss, chosen_mean_scores, rejected_mean_scores = self.forward_loss(input_a["decoder_input_ids"], value_a,
                                                                               input_b["decoder_input_ids"], value_b)
            loss_dict = {
                "loss": loss,
                "chosen_mean_scores": chosen_mean_scores.mean(),
                "rejected_mean_scores": rejected_mean_scores.mean()
            }
            if self.training:
                return (loss_dict,)
            return (loss, value_a, value_b)

        values, chosen_mean_scores = self.forward_value(batch["decoder_input_ids"], value_a)
        if return_value_only:
            return (values,)
        return (values, chosen_mean_scores)




class MyRewardTransformer(MyRewardModel, with_pl=True):
    def __init__(self, *args, **kwargs):
        lora_args: LoraConfig = kwargs.pop('lora_args', None)
        super(MyRewardTransformer, self).__init__(*args, **kwargs)
        self.lora_args = lora_args
        if lora_args is not None and lora_args.with_lora:
            model = LoraModel(self.backbone, lora_args)
            print('*' * 30, 'lora info')
            model.print_trainable_parameters()
            self.set_model(model, copy_attr=False)

    def get_llm_model(self) -> PreTrainedModel:
        if self.lora_args is not None and self.lora_args.with_lora:
            return self.backbone.model.model
        return self.backbone.model


    def forward_returns(self,*args,**kwargs):
        if self.lora_args is not None and self.lora_args.with_lora:
            model = self.backbone.model
        else:
            model = self.backbone
        return model.forward_returns(*args,**kwargs)


class MyPPOTransformer(AutoModelForSeq2SeqLMWithValueHead,PPOModelLoss, with_pl=True):
    def __init__(self, *args, **kwargs):
        lora_args: LoraConfig = kwargs.pop('lora_args', None)
        ppo_args: PPOConfig = kwargs.pop('ppo_args', None)
        super(MyPPOTransformer, self).__init__(*args, **kwargs)

        self.lora_args = lora_args
        self.ppo_config = ppo_args
        if lora_args is not None and lora_args.with_lora:
            model = LoraModel(self.backbone, lora_args)
            print('*' * 30, 'lora info')
            model.print_trainable_parameters()
            self.set_model(model, copy_attr=False)


    def get_llm_model(self) -> PreTrainedModel:
        if self.lora_args is not None and self.lora_args.with_lora:
            return self.backbone.model.model
        return self.backbone.model

    @torch.no_grad()
    def generate(self,*args,**kwargs):
        return self.get_llm_model().generate(*args,**kwargs)

    def configure_optimizers(self):
        p = self.get_named_parameters(self.backbone)
        training_args = self.training_args
        optimizer = AdamW(p, lr=training_args.learning_rate,
                          eps=training_args.adam_epsilon,
                          betas=training_args.optimizer_betas,
                          weight_decay=training_args.weight_decay)
        return optimizer


    def training_step(self,*args, **inputs):
        outputs = self.compute_loss(*args, **inputs)
        return outputs

    def validation_step(self, batch):
        outputs = self.compute_loss(**batch)
        return outputs

    def compute_loss(self, *args, **inputs):
        return self.forward_ppo_loss(*args, **inputs)


    def forward_logits_values(self,*args,**kwargs):
        return self.model.forward(*args,**kwargs)





def load_reward_model(model_dir) ->MyRewardTransformer:
    parser = HfArgumentParser((ModelArguments, TrainingArguments, DataArguments, LoraArguments))
    model_args, training_args, data_args, lora_args = parser.parse_dict(reward_config.train_info_args)
    lora_args = lora_args.config
    config = AutoConfig.from_pretrained(model_dir)
    # 加载权重
    lora_args = LoraArguments.from_pretrained(model_dir)
    pl_module = MyRewardTransformer(config=config,model_args=model_args,training_args=training_args,lora_args=lora_args)
    # 加载lora权重
    pl_module.backbone.from_pretrained(pl_module.backbone.model, pretrained_model_name_or_path=model_dir,lora_config=lora_args)
    pl_module.eval()
    pl_module.requires_grad_(False)
    return pl_module


def load_ref_model(lora_model_dir,ref_train_info_args) ->MyPPOTransformer:
    parser = HfArgumentParser((ModelArguments, TrainingArguments, DataArguments, LoraArguments))
    model_args, training_args, data_args, lora_args = parser.parse_dict(ref_train_info_args)
    lora_args = lora_args.config
    config = AutoConfig.from_pretrained(lora_model_dir)
    # 加载权重
    lora_args = LoraArguments.from_pretrained(lora_model_dir)
    pl_module = MyPPOTransformer(config=config,model_args=model_args,training_args=training_args,lora_args=lora_args)
    # 二次加载权重
    pl_module.backbone.from_pretrained(pl_module.backbone.model, pretrained_model_name_or_path=lora_model_dir,lora_config=lora_args)
    pl_module.eval()
    pl_module.requires_grad_(False)
    return pl_module