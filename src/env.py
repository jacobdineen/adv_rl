# -*- coding: utf-8 -*-
"""
main environment logic
to be used downstream for model trianing
"""
import logging
from typing import Any, Dict, Tuple

import gym
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as F
from gym import spaces
from torch.utils.data import DataLoader
from torchvision import transforms
from torchvision.datasets import CIFAR10
from torchvision.models import resnet50

logging.basicConfig(level=logging.INFO)


class ImagePerturbEnv(gym.Env):
    """
    A custom gym environment for perturbing images and evaluating the changes
    against a deep learning model.

    Attributes:
        dataloader (iter): An iterator over a PyTorch DataLoader.
        model (torch.nn.Module): The deep learning model to test against.
        attack_budget (int): The number of actions to perturb the image.
        current_attack_count (int): Counter for perturbation actions.
        action_space (gym.spaces.Discrete): The action space.
        observation_space (gym.spaces.Box): The observation space.
        image (torch.Tensor): The current image from the dataloader.
        target_class (int): The class label for the current image.
        image_shape (Tuple[int, int, int]): The shape of the image tensor.
    """

    def __init__(self, dataloader: Any, model: torch.nn.Module, attack_budget: int = 20, lambda_: float = 1.0):
        """
        Initialize the environment.

        Args:
            dataloader: PyTorch DataLoader iterator.
            model: The deep learning model to evaluate against.
            attack_budget: The number of steps available to perturb the image.
            lambda_: hyperparameter that controls how severely we penalize non-sparse solutions. A higher LAMBDA means a steeper penalty.
        """
        self.dataloader = iter(dataloader)
        self.model = model
        self.model.eval()  # inference mode only for these models
        self.image, self.target_class = next(self.dataloader)  # start with an image in queue
        self.original_image = self.image.clone()  # Save the original image
        self.image_shape = self.image.shape  # torch.Size([1, 3, 224, 224]) for cifar
        total_actions = self.image_shape[1] * self.image_shape[2] * self.image_shape[3]
        self.action_space = spaces.Discrete(total_actions)
        self.observation_space = spaces.Box(low=0, high=1, shape=self.image_shape, dtype=np.float32)
        self.attack_budget = attack_budget
        self.lambda_ = lambda_
        self.current_attack_count = 0

        logging.info(f"Initialized ImagePerturbEnv with the following parameters:")
        logging.info(f"Action Space Size: {total_actions}")
        logging.info(f"Observation Space Shape: {self.observation_space.shape}")
        logging.info(f"Attack Budget: {self.attack_budget}")
        logging.info(f"Initial Image Shape: {self.image_shape}")

    def step(self, action: int) -> Tuple[torch.Tensor, float, bool, Dict[str, Any]]:
        """
        Take a step using an action.

        Args:
            action: An integer action from the action space.
            Currently - an action corresponds to shutting an (x,y) coordinate across ALL channels
            So one step modifies three separate pixels

        Returns:
            Tuple: A tuple containing:
                - perturbed_image: The new state (perturbed image)
                - reward: The reward for the taken action
                - done: Flag indicating if the episode has ended
                - info: Additional information (empty in this case)
        """
        self.current_attack_count += 1

        perturbed_image = self.image.clone()

        channel, temp = divmod(
            action, self.image_shape[2] * self.image_shape[3]
        )  # channel, x*y coordinates in the image
        x, y = divmod(temp, self.image_shape[3])  # x, y coordinates in the image
        perturbed_image[0, channel, x, y] = 0  # perturb the image by setting the pixel to 0

        reward = self.compute_reward(self.image, perturbed_image)

        done = self.current_attack_count >= self.attack_budget  # continue until attack budget reached
        if done:
            logging.info("attack budget reached. Sampling new image")
            self.reset()

        self.image = perturbed_image

        return perturbed_image, reward, done, {}

    def compute_reward(self, original_image: torch.Tensor, perturbed_image: torch.Tensor) -> float:
        """_summary_

        Args:
            original_image (torch.Tensor): og image
            perturbed_image (torch.Tensor): perturbed_image

        Returns:
            float: reward for step
        """
        with torch.no_grad():
            original_output = self.model(original_image)
            original_prob = F.softmax(original_output, dim=1)[0][self.target_class].item()

            perturbed_output = self.model(perturbed_image)
            perturbed_prob = F.softmax(perturbed_output, dim=1)[0][self.target_class].item()

        sparsity = torch.nonzero(perturbed_image - original_image).size(0)
        reward = (original_prob - perturbed_prob) * np.exp(-self.lambda_ * sparsity)

        return reward

    def reset(self) -> torch.Tensor:
        """
        Reset the environment state.

        Returns:
            The new state (image) after resetting.
        """
        self.image, self.target_class = next(self.dataloader)
        self.original_image = self.image.clone()  # Save the original image again
        self.current_attack_count = 0

        return self.image


if __name__ == "__main__":
    # This is mainly just for testing
    # but can likely be lifted for other parts of the codebase

    transform_chain = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
        ]
    )

    dataset = CIFAR10(root="./data", train=True, download=True, transform=transform_chain)
    dataloader = DataLoader(dataset, batch_size=1, shuffle=True)

    model = resnet50(pretrained=True)
    env = ImagePerturbEnv(dataloader=dataloader, model=model)

    num_steps = env.attack_budget - 1
    for _ in range(num_steps):
        original_image = env.image.clone().detach().cpu().numpy().squeeze()
        action = env.action_space.sample()
        next_state, reward, done, _ = env.step(action)
        perturbed_image = next_state.clone().detach().cpu().numpy().squeeze()
        if done:
            env.reset()

    with torch.no_grad():
        original_output = model(env.original_image)
        original_prob, original_class = F.softmax(original_output, dim=1).max(dim=1)

        perturbed_output = model(env.image)
        perturbed_prob, perturbed_class = F.softmax(perturbed_output, dim=1).max(dim=1)

        # print(f"Original Model Output: {original_output}")
        print(f"Original Model class and Probability: {original_class.item()}, {original_prob.item()}")

        # print(f"Perturbed Model Output: {perturbed_output}")
        print(f"Perturbed Model class and Probability: {perturbed_class.item()}, {perturbed_prob.item()}")

    original_image = env.original_image.clone().detach().cpu().numpy().squeeze()
    perturbed_image = next_state.clone().detach().cpu().numpy().squeeze()

    changed_pixels = np.where(original_image != perturbed_image)
    print(f"Number of pixels changed: {len(changed_pixels[0])}")
    print("Shape of original_image: ", original_image.shape)
    print("Shape of perturbed_image: ", perturbed_image.shape)
    print("Length of changed_pixels tuple: ", len(changed_pixels))

    # Since you only have 3 dimensions [channel, height, width]
    for i in range(len(changed_pixels[0])):
        channel_idx, x_idx, y_idx = changed_pixels[0][i], changed_pixels[1][i], changed_pixels[2][i]
        pixel_value = perturbed_image[channel_idx, x_idx, y_idx].item()
        print(f"Pixel value in perturbed image at ({x_idx}, {y_idx}, channel: {channel_idx}): {pixel_value}")

    original_image_T = np.transpose(original_image, (1, 2, 0))
    highlighted_isolated = np.zeros_like(original_image_T)
    for i in range(len(changed_pixels[0])):
        channel_idx, x_idx, y_idx = changed_pixels[0][i], changed_pixels[1][i], changed_pixels[2][i]
        # Set the RGB value based on the channel index
        if channel_idx == 0:
            highlighted_isolated[x_idx, y_idx, :] = [255, 0, 0]  # Red for channel 0
        elif channel_idx == 1:
            highlighted_isolated[x_idx, y_idx, :] = [0, 255, 0]  # Green for channel 1
        elif channel_idx == 2:
            highlighted_isolated[x_idx, y_idx, :] = [0, 0, 255]  # Blue for channel 2

    plt.figure()
    plt.subplot(1, 3, 1)
    plt.title(f"Original (Class: {original_class.item()}, Prob: {original_prob.item():.10f})")
    plt.imshow(np.transpose(original_image, (1, 2, 0)))

    plt.subplot(1, 3, 2)
    plt.title(f"Perturbed (Class: {perturbed_class.item()}, Prob: {perturbed_prob.item():.10f})")
    plt.imshow(np.transpose(perturbed_image, (1, 2, 0)))

    plt.subplot(1, 3, 3)
    plt.title("Highlighted Changes")
    plt.imshow(highlighted_isolated)
    # Create custom handles for the legend
    ax = plt.gca()
    ax.annotate("Channel 0: Red", xy=(1.1, 0.2), xycoords="axes fraction", color="red")
    ax.annotate("Channel 1: Green", xy=(1.1, 0.3), xycoords="axes fraction", color="green")
    ax.annotate("Channel 2: Blue", xy=(1.1, 0.4), xycoords="axes fraction", color="blue")

    plt.show()

    # plt.subplot(1, 3, 3)
    # plt.title('Highlighted')
    # plt.imshow(np.transpose(highlighted_image, (1, 2, 0)).squeeze())
    plt.show()
