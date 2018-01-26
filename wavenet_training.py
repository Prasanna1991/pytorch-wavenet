import torch
import torch.optim as optim
import torch.utils.data
import time
from datetime import datetime
import torch.nn.functional as F
from torch.autograd import Variable
from model_logging import Logger
from wavenet_modules import *


def print_last_loss(opt):
    print("loss: ", opt.losses[-1])


def print_last_validation_result(opt):
    print("validation loss: ", opt.validation_results[-1])


class WavenetTrainer:
    def __init__(self,
                 model,
                 dataset,
                 optimizer=optim.Adam,
                 lr=0.001,
                 weight_decay=0,
                 gradient_clipping=None,
                 logger=Logger(),
                 snapshot_path=None,
                 snapshot_name='snapshot',
                 snapshot_interval=1000,
                 snapshot_callback=None,
                 dtype=torch.FloatTensor,
                 ltype=torch.LongTensor,
                 num_workers=8,
                 pin_memory=False,
                 process_batch=None):
        self.model = model
        self.dataset = dataset
        self.dataloader = None
        self.lr = lr
        self.weight_decay = weight_decay
        self.clip = gradient_clipping
        self.optimizer_type = optimizer
        self.optimizer = self.optimizer_type(params=self.model.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        self.logger = logger
        self.logger.trainer = self
        self.snapshot_path = snapshot_path
        self.snapshot_name = snapshot_name
        self.snapshot_interval = snapshot_interval
        self.snapshot_callback = snapshot_callback
        self.dtype = dtype
        self.ltype = ltype
        self.num_workers = num_workers
        self.pin_memory = pin_memory
        self.process_batch = process_batch

    def train(self,
              batch_size=32,
              epochs=10,
              continue_training_at_step=0):
        self.model.train()
        self.dataloader = torch.utils.data.DataLoader(self.dataset,
                                                      batch_size=batch_size,
                                                      shuffle=True,
                                                      num_workers=self.num_workers,
                                                      pin_memory=self.pin_memory)
        step = continue_training_at_step
        num_step_track = 10
        step_times = np.zeros(num_step_track)
        for current_epoch in range(epochs):
            print("epoch", current_epoch)
            tic = time.time()
            for batch in iter(self.dataloader):
                if self.process_batch is None:
                    x, target = batch
                    x = Variable(x.type(self.dtype))
                    target = Variable(target.type(self.ltype))
                else:
                    x, target = self.process_batch(batch, self.dtype, self.ltype)

                output = self.model(x)
                target = target.view(-1)
                loss = F.cross_entropy(output.squeeze(), target.squeeze())
                self.optimizer.zero_grad()
                loss.backward()
                loss = loss.data[0]

                if self.clip is not None:
                    torch.nn.utils.clip_grad_norm(self.model.parameters(), self.clip)
                self.optimizer.step()
                step += 1

                # time step duration:
                if step <= num_step_track:
                    toc = time.time()
                    step_times[step-1] = toc - tic
                    tic = time.time()
                    if step == num_step_track:
                        mean = np.mean(step_times)
                        std = np.std(step_times)
                        print("one training step does take " + str(mean) + " +/- " + str(std) + " seconds")

                if step % self.snapshot_interval == 0:
                    if self.snapshot_path is None:
                        continue
                    time_string = time.strftime("%Y-%m-%d_%H-%M-%S", time.gmtime())
                    torch.save(self.model, self.snapshot_path + '/' + self.snapshot_name + '_' + time_string)
                    if self.snapshot_callback is not None:
                        self.snapshot_callback()

                self.logger.log(step, loss)

    def validate(self):
        self.model.eval()
        self.dataset.train = False
        total_loss = 0
        accurate_classifications = 0
        for (x, target) in iter(self.dataloader):
            x = Variable(x.type(self.dtype))
            target = Variable(target.view(-1).type(self.ltype))

            output = self.model(x)
            loss = F.cross_entropy(output.squeeze(), target.squeeze())
            total_loss += loss.data[0]

            predictions = torch.max(output, 1)[1].view(-1)
            correct_pred = torch.eq(target, predictions)
            accurate_classifications += torch.sum(correct_pred).data[0]
        # print("validate model with " + str(len(self.dataloader.dataset)) + " samples")
        # print("average loss: ", total_loss / len(self.dataloader))
        avg_loss = total_loss / len(self.dataloader)
        avg_accuracy = accurate_classifications / (len(self.dataset)*self.dataset.target_length)
        self.dataset.train = True
        self.model.train()
        return avg_loss, avg_accuracy


def generate_audio(model,
                   length=8000,
                   temperatures=[0., 1.]):
    samples = []
    for temp in temperatures:
        samples.append(model.generate_fast(length, temperature=temp))
    samples = np.stack(samples, axis=0)
    return samples

