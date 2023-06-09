## update information
- [deep_training](https://github.com/ssbuild/deep_training)

```text
    06-13 support resize_token_embeddings
    06-01 support deepspeed training for lora adalora prompt,0.1.9 和 0.1.10合并
    05-27 add qlora transformers>=4.30
```
## install
    python >= 3.10
- pip install -U -r requirements.txt
- 如果无法安装， 可以切换官方源 pip install -i https://pypi.org/simple -U -r requirements.txt


    


## 预训练模型下载
    
- [ChatYuan-large-v1](https://huggingface.co/ClueAI/ChatYuan-large-v1)
- [ChatYuan-large-v2](https://huggingface.co/ClueAI/ChatYuan-large-v2)


## 数据示例

```json
{
	"prompt": "\n\nHuman:你能描述如何清除笔记本计算机屏幕上的指纹和污垢的步骤吗?\n\nAssistant:是的,也许。为了清洁你的屏幕,你首先需要使用微纤维布或软溼布,轻轻地擦拭屏幕表面。接下来,你会想抓住一个软,无毛巾,微纤维清洁布,轻轻地擦回屏幕上去除指纹和污垢。\n\nHuman:我可以将伊索普罗素酒精喷射到布上,并以这种方式清洗它吗?\n\nAssistant:",
	"response": " 是的,你可以这样做,以帮助布从屏幕上收集更多的污垢。 请确保始终使用干净的软布,而不是一块粗糙的、粗糙的或结构化的材料,并确保它是无毛布的。",
	"chosen": " 是的,你可以这样做,以帮助布从屏幕上收集更多的污垢。 请确保始终使用干净的软布,而不是一块粗糙的、粗糙的或结构化的材料,并确保它是无毛布的。",
	"rejected": " 是的,你可以直接将它喷射到布上。"
}
```

## 训练参数
[训练参数](args.MD)


## infer
    # infer_finetuning.py 推理微调模型
    # infer_lora_finetuning.py 推理微调模型
     python infer_finetuning.py



## training
```text
    #制作数据
    python data_utils.py
    注: num_process_worker 为多进程制作数据 ， 如果数据量较大 ， 适当调大至cpu数量
    dataHelper.make_dataset_with_args(data_args.train_file,mixed_data=False, shuffle=True,mode='train',num_process_worker=0)
    
    #训练
    python train.py
```

## 训练参数
[训练参数](args.MD)

## 友情链接

- [pytorch-task-example](https://github.com/ssbuild/pytorch-task-example)
- [tf-task-example](https://github.com/ssbuild/tf-task-example)
- [chatmoss_finetuning](https://github.com/ssbuild/chatmoss_finetuning)
- [chatglm_finetuning](https://github.com/ssbuild/chatglm_finetuning)
- [chatyuan_finetuning](https://github.com/ssbuild/chatyuan_finetuning)
- [llm_finetuning](https://github.com/ssbuild/llm_finetuning)
- [rlhf_llm](https://github.com/ssbuild/rlhf_llm)
- [rlhf_chatglm](https://github.com/ssbuild/rlhf_chatglm)
- [rlhf_chatyuan](https://github.com/ssbuild/rlhf_chatyuan)
- [rwkv_finetuning](https://github.com/ssbuild/rwkv_finetuning)

## 
    纯粹而干净的代码