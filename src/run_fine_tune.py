import torch
from torch.optim import AdamW
from transformers import get_scheduler
import logging
import math
from tqdm import tqdm

from models import build_model_tokenizer, prepare_model_kwargs
from data import prepare_data
import configs

logger = logging.getLogger(__name__)


def run_eval(args, model, tokenizer, dataloader, is_test=False):

    model.eval()

    eval_bar = tqdm(dataloader, total=len(dataloader), desc="Testing" if is_test else "Validating")
    for step, batch in enumerate(eval_bar):
        model_kwargs = prepare_model_kwargs(args, batch)
        if args.task in configs.TASK_TYPE_TO_LIST["classification"]:
            loss, logits = model()



def run_fine_tune(args):

    logger.info("=" * 20 + " LOADING " + "=" * 20)

    model, tokenizer = build_model_tokenizer(args)

    # watch model
    args.run.watch(model, log_freq=10)

    # prepare data for training and validation
    if args.do_train:
        train_examples, train_dataset, train_dataloader = prepare_data(args, split="train", tokenizer=tokenizer)
    if args.do_valid:
        valid_examples, valid_dataset, valid_dataloader = prepare_data(args, split="valid", tokenizer=tokenizer)

    logger.info(f"Data is loaded and prepared")

    if args.do_train:
        logger.info("=" * 20 + " TRAINING " + "=" * 20)
        # Optimizer
        # Split weights in two groups, one with weight decay and the other not
        no_decay = ["bias", "LayerNorm.weight"]
        optimizer_grouped_parameters = [
            {
                "params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)],
                "weight_decay": args.weight_decay,
            },
            {
                "params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)],
                "weight_decay": 0.0,
            },
        ]
        optimizer = AdamW(optimizer_grouped_parameters, lr=args.learning_rate)

        # Prepare everything with accelerator
        model, optimizer, train_dataloader = args.accelerator.prepare(model, optimizer, train_dataloader)
        if args.do_valid:
            valid_dataloader = args.accelerator.prepare(valid_dataloader)

        num_update_steps_per_epoch = math.ceil(len(train_dataloader) / args.gradient_accumulation_steps)
        if args.max_train_steps is None:
            args.max_train_steps = args.num_train_epochs * num_update_steps_per_epoch
        else:
            args.num_train_epochs = math.ceil(args.max_train_steps / num_update_steps_per_epoch)

        # Scheduler and math around the number of training steps
        lr_scheduler = get_scheduler(
            name=args.lr_scheduler_type,
            optimizer=optimizer,
            num_warmup_steps=args.num_warmup_steps,
            num_training_steps=args.max_train_steps,
        )

        total_batch_size = args.train_batch_size * args.accelerator.num_processes * args.gradient_accumulation_steps

        logger.info("***** Running training *****")
        logger.info(f"  Num examples = {len(train_dataset)}")
        logger.info(f"  Num Epochs = {args.num_train_epochs}")
        logger.info(f"  Instantaneous batch size per device = {args.per_device_train_batch_size}")
        logger.info(f"  Total train batch size (w. parallel, distributed & accumulation) = {total_batch_size}")
        logger.info(f"  Gradient Accumulation steps = {args.gradient_accumulation_steps}")
        logger.info(f"  Total optimization steps = {args.max_train_steps}")

        # Only show the progress bar once on each machine.
        completed_steps = 0

        for epoch in range(args.num_train_epochs):
            model.train()

            train_bar = tqdm(train_dataloader, total=len(train_dataloader), desc=f"[epoch {epoch}, loss x.xxxx]")
            for step, batch in enumerate(train_bar):
                model_kwargs = prepare_model_kwargs(args, batch)
                outputs = model(**model_kwargs)

                loss = outputs.loss
                loss = loss / args.gradient_accumulation_steps
                args.accelerator.backward(loss)

                train_bar.set_description(f"[epoch {epoch}, loss {loss.item():.4f}]")
                args.run.log({"train_loss": loss.item()})

                if step % args.gradient_accumulation_steps == 0 or step == len(train_dataloader) - 1:
                    optimizer.step()
                    lr_scheduler.step()
                    optimizer.zero_grad()
                    completed_steps += 1

                if completed_steps >= args.max_train_steps:
                    break

            if args.do_valid:





