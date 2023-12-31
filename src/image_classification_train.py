# -*- coding: utf-8 -*-
import argparse
import gc
import logging

import torch
from torch import nn
from torchvision import datasets, transforms
from torchvision.models import resnet18
from tqdm import tqdm

from src.classifiers import DQNDNN

logging.basicConfig(level=logging.INFO)


def train_model(dataset_name, save_path, batch_size, num_epochs):
    # Set the device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Define a transform to normalize the data
    transform = transforms.Compose(
        [
            transforms.ToTensor(),  # Converts PIL image or numpy.ndarray to tensor
            transforms.Normalize((0.5,), (0.5,)),  # Normalize the data
        ]
    )

    # Download and load the dataset
    if dataset_name.lower() == "mnist":
        logging.info(f"====> Loading {dataset_name} data")
        train_set = datasets.MNIST("./data", train=True, download=True, transform=transform)
        test_set = datasets.MNIST("./data", train=False, download=True, transform=transform)
        train_loader = torch.utils.data.DataLoader(train_set, batch_size=batch_size, shuffle=True)
        test_loader = torch.utils.data.DataLoader(test_set, batch_size=batch_size, shuffle=False)
        model = resnet18(num_classes=10)
        model.conv1 = nn.Conv2d(1, 64, kernel_size=(7, 7), stride=(2, 2), padding=(3, 3), bias=False)
        model = model.to(device)
    elif dataset_name.lower() == "cifar":
        # Handle other datasets if needed
        logging.info(f"====> Loading {dataset_name} data")
        transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        )
        train_set = datasets.CIFAR10("./data", train=True, download=True, transform=transform)
        test_set = datasets.CIFAR10("./data", train=False, download=True, transform=transform)
        train_loader = torch.utils.data.DataLoader(train_set, batch_size=batch_size, shuffle=True)
        test_loader = torch.utils.data.DataLoader(test_set, batch_size=batch_size, shuffle=False)
        # model = resnet18(num_classes=10)
        model = resnet18(pretrained=True)  # This loads the model with pre-trained weights
        num_ftrs = model.fc.in_features
        model.fc = torch.nn.Linear(num_ftrs, 10)  # 10 classes for CIFAR-10

        model = model.to(device)
    elif dataset_name.lower() == "mnist2":
        logging.info(f"====> Loading {dataset_name} data")
        train_set = datasets.MNIST("./data", train=True, download=True, transform=transform)
        # test_set = datasets.MNIST(
        #     "./data", train=False, download=True, transform=transform
        # )
        train_loader = torch.utils.data.DataLoader(train_set, batch_size=batch_size, shuffle=True)
        # test_loader = torch.utils.data.DataLoader(
        #     test_set, batch_size=batch_size, shuffle=False
        # )
        # Initialize the DQNDNN model
        model = DQNDNN()
        model = model.to(device)

    # Other hyperparameters and optimizer setup
    learning_rate = 0.001
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=0.001)
    logging.info(f"====> num_epochs: {num_epochs}")
    logging.info(f"====> learning_rate: {learning_rate}")
    logging.info(f"====> Started training Resnet-18 {dataset_name} model")
    logging.info(f"====> using device: {device}")
    # total_step = len(train_loader)

    for epoch in tqdm(range(num_epochs)):
        for _, (images, labels) in tqdm(enumerate(train_loader)):
            # Move tensors to the configured device
            images = images.to(device)
            labels = labels.to(device)

            # Forward pass
            outputs = model(images)
            loss = criterion(outputs, labels)

            # Backward and optimize
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            del images, labels, outputs
            torch.cuda.empty_cache()
            gc.collect()
        logging.info("Epoch [{}/{}], Loss: {:.4f}".format(epoch + 1, num_epochs, loss.item()))

    # do evaluation over test set
    total_correct = 0
    total_samples = 0
    with torch.no_grad():  # Disable gradient computation
        for images, labels in test_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)  # Get raw output from the model
            _, predicted = torch.max(outputs, 1)  # Get the predicted labels

            total_correct += (predicted == labels).sum().item()
            total_samples += labels.size(0)

    accuracy = total_correct / total_samples
    logging.info(f"====> Accuracy over the test set: {accuracy * 100:.2f}%")

    # Save the model with the dataset name
    logging.info(f"====> Finished training {dataset_name} model")
    logging.info(f"====> Saving {dataset_name} model to {save_path}_{dataset_name}.pth")
    torch.save(model.state_dict(), f"{save_path}_{dataset_name}.pth")
    logging.info(f"====> Saved {dataset_name} model to {save_path}_{dataset_name}.pth")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train a model with a specific dataset")
    parser.add_argument("dataset_name", type=str, help="Name of the dataset")
    parser.add_argument("location_path", type=str, help="Path to save the model")
    parser.add_argument("--batch_size", type=int, default=64, help="Batch size for training")
    parser.add_argument("--num_epochs", type=int, default=1, help="Number of epochs for training")
    args = parser.parse_args()

    train_model(args.dataset_name, args.location_path, args.batch_size, args.num_epochs)
