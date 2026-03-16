# SwarmPY
Web API for Docker Swarm, written in Python. It also servers a minimalist GUI.

## Audience

For those who consider k8s as an overkill for a lightweight, few-nodes cluster.

## Motivation

SwarmPit is dead, Portainer is expensive.

## Purpose

To have a simple web interface managing stacks and services.

## What it is

A no-authentication web service which must be behind your load balancer.

## What it is not

A container manager. There are million versions on the Internet.

# API documentation

Start your container:

`docker run -it --rm --name swarmpit  -v /var/run/docker.sock:/var/run/docker.sock -p 8080:8080 ghcr.io/zsbt/swarmpy:main`

Then visit http://IP:8080/docs
