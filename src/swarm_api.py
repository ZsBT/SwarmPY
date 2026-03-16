# vim: set ft=python ts=4 sw=4 et:
"""
Docker Swarm REST API Server
Exposes Docker Swarm state via JSON REST endpoints.
Requires: pip install fastapi uvicorn docker
"""

import docker
import uvicorn

from fastapi import Body, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from docker.errors import DockerException

app = FastAPI(title="Docker Swarm API", version="0.1.0")

app.mount("/static", StaticFiles(directory="static"), name="static")

class DockerClient:
    """Wrapper around the Docker SDK client."""

    def __init__(self):
        try:
            self._client = docker.from_env()
        except DockerException as e:
            raise RuntimeError(f"Cannot connect to Docker socket: {e}") from e

    @property
    def client(self) -> docker.DockerClient:
        return self._client


class StackService:
    """Business logic for Docker stack operations."""

    def __init__(self, docker_client: DockerClient):
        self._client = docker_client.client

    def list_stacks(self) -> list[dict]:
        """
        Emulates `docker stack ls` by inspecting service labels.
        Services belonging to a stack carry the label
        'com.docker.stack.namespace'.
        """
        try:
            services = self._client.services.list()
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        stacks: dict[str, int] = {}
        for svc in services:
            namespace = svc.attrs.get("Spec", {}).get("Labels", {}).get(
                "com.docker.stack.namespace"
            )
            if namespace:
                stacks[namespace] = stacks.get(namespace, 0) + 1

        return [{"name": name, "services": count} for name, count in sorted(stacks.items())]


    def delete_stack(self, name: str) -> dict:
        """
        Emulates `docker stack rm <name>` by removing all services
        whose 'com.docker.stack.namespace' label matches `name`.
        """
        try:
            services = self._client.services.list(
                filters={"label": f"com.docker.stack.namespace={name}"}
            )
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        if not services:
            raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

        removed = []
        errors = []
        for svc in services:
            try:
                svc.remove()
                removed.append(svc.name)
            except DockerException as e:
                errors.append({"service": svc.name, "error": str(e)})

        return {"stack": name, "removed": removed, "errors": errors}


    def list_stack_services(self, name: str) -> list[dict]:
        """
        Emulates `docker stack services <name>`.
        """
        try:
            services = self._client.services.list(
                filters={"label": f"com.docker.stack.namespace={name}"}
            )
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        if not services:
            raise HTTPException(status_code=404, detail=f"Stack '{name}' not found")

        result = []
        for svc in services:
            spec = svc.attrs.get("Spec", {})
            mode_spec = spec.get("Mode", {})
            task_template = spec.get("TaskTemplate", {})
            image = task_template.get("ContainerSpec", {}).get("Image", "").split("@")[0]  # strip digest

            # Mode + replicas
            if "Replicated" in mode_spec:
                mode = "replicated"
                desired = mode_spec["Replicated"].get("Replicas", 0)
            elif "Global" in mode_spec:
                mode = "global"
                desired = None  # calculated from running tasks
            else:
                mode = "unknown"
                desired = None

            # Running tasks
            try:
                tasks = svc.tasks(filters={"desired-state": "running"})
                running = sum(1 for t in tasks if t["Status"]["State"] == "running")
            except DockerException:
                running = 0

            if mode == "global" and desired is None:
                desired = running  # best approximation without node count

            replicas = f"{running}/{desired}"

            # Ports
            endpoint = svc.attrs.get("Endpoint", {})
            ports = []
            for p in endpoint.get("Ports", []):
                published = p.get("PublishedPort")
                target = p.get("TargetPort")
                protocol = p.get("Protocol", "tcp")
                if published:
                    ports.append(f"*:{published}->{target}/{protocol}")

            result.append({
                "id": svc.short_id,
                "name": svc.name,
                "mode": mode,
                "replicas": {"desired": desired, "running": running},
                "image": image,
                "ports": ports,
            })

        return result




class ServiceService:
    """Business logic for Docker service operations."""

    def __init__(self, docker_client: DockerClient):
        self._client = docker_client.client

    def list_services(self) -> list[dict]:
        """
        Emulates `docker service ls`.
        """
        try:
            services = self._client.services.list()
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        result = []
        for svc in services:
            spec = svc.attrs.get("Spec", {})
            mode_spec = spec.get("Mode", {})
            task_template = spec.get("TaskTemplate", {})
            image = task_template.get("ContainerSpec", {}).get("Image", "").split("@")[0]

            if "Replicated" in mode_spec:
                mode = "replicated"
                desired = mode_spec["Replicated"].get("Replicas", 0)
            elif "Global" in mode_spec:
                mode = "global"
                desired = None
            else:
                mode = "unknown"
                desired = None

            try:
                tasks = svc.tasks(filters={"desired-state": "running"})
                running = sum(1 for t in tasks if t["Status"]["State"] == "running")
            except DockerException:
                running = 0

            if mode == "global" and desired is None:
                desired = running

            endpoint = svc.attrs.get("Endpoint", {})
            ports = []
            for p in endpoint.get("Ports", []):
                published = p.get("PublishedPort")
                target = p.get("TargetPort")
                protocol = p.get("Protocol", "tcp")
                if published:
                    ports.append(f"*:{published}->{target}/{protocol}")

            result.append({
                "name": svc.name,
                "id": svc.short_id,
                "mode": mode,
                "replicas": {"desired": desired, "running": running},
                "image": image,
                "ports": ports,
            })

        return result


    def get_service_tasks(self, name_or_id: str) -> list[dict]:
        """
        Emulates `docker service ps <name|id>`.
        """
        try:
            svc = self._client.services.get(name_or_id)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service '{name_or_id}' not found")
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        try:
            tasks = svc.tasks()
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        result = []
        for t in tasks:
            status = t.get("Status", {})
            desired = t.get("DesiredState", "")
            node_id = t.get("NodeID", "")

            try:
                node = self._client.nodes.get(node_id)
                node_hostname = node.attrs.get("Description", {}).get("Hostname", node_id[:12])
            except DockerException:
                node_hostname = node_id[:12]

            slot = t.get("Slot")
            image = (
                t.get("Spec", {})
                 .get("ContainerSpec", {})
                 .get("Image", "")
                 .split("@")[0]
            )

            current_state = status.get("State", "")

            if not current_state == 'shutdown':
                result.append({
                    "id": t["ID"][:12],
                    "name": f"{svc.name}.{slot or node_id[:12]}",
                    "image": image,
                    "node": node_hostname,
                    "desired_state": desired,
                    "current_state": current_state,
                    "message": status.get("Message", ""),
                    "error": status.get("Err", ""),
                    "timestamp": status.get("Timestamp", ""),
                })

        return result


    def delete_service(self, name_or_id: str) -> dict:
        """
        Emulates `docker service rm <name|id>`.
        """
        try:
            svc = self._client.services.get(name_or_id)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service '{name_or_id}' not found")
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        try:
            svc.remove()
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"deleted": svc.name, "id": svc.short_id}


    def rollback_service(self, name_or_id: str) -> dict:
        """
        Emulates `docker service rollback <name|id>`.
        """
        try:
            svc = self._client.services.get(name_or_id)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service '{name_or_id}' not found")
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        try:
            svc.reload()
            spec = svc.attrs.get("PreviousSpec")
            if not spec:
                raise HTTPException(status_code=409, detail="No previous spec available for rollback")
            svc.update(rollback_config={"Order": "start-first"}, fetch_current_spec=True)
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"rolled_back": svc.name, "id": svc.short_id}


    def update_service(self, name_or_id: str, image: str | None = None) -> dict:
        """
        Emulates `docker service update [--image <image>] --force <name|id>`.
        Always forces update; optionally changes the image tag.
        """
        try:
            svc = self._client.services.get(name_or_id)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service '{name_or_id}' not found")
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        try:
            kwargs = {"force_update": True}
            if image:
                kwargs["image"] = image
                svc.update(**kwargs)
            else:
                self.force_pull_update(name_or_id)
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"updated": svc.name, "id": svc.short_id, "image": image or "unchanged"}


    def force_pull_update(self, name_or_id: str) -> dict:
        """
        Pulls the current image from the registry to resolve the latest digest,
        then updates the service pinned to that digest — forcing all nodes to pull.
        """
        try:
            svc = self._client.services.get(name_or_id)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service '{name_or_id}' not found")
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        image_str = (
            svc.attrs.get("Spec", {})
               .get("TaskTemplate", {})
               .get("ContainerSpec", {})
               .get("Image", "")
               .split("@")[0]   # strip any existing digest
        )
        if not image_str:
            raise HTTPException(status_code=500, detail="Could not determine service image")

        # Split name and tag
        tag   = "latest"
        image = image_str
        if ":" in image_str.split("/")[-1]:
            image, tag = image_str.rsplit(":", 1)

        try:
            pulled = self._client.images.pull(image, tag=tag)
        except DockerException as e:
            raise HTTPException(status_code=500, detail=f"Pull failed: {e}")

        digests = pulled.attrs.get("RepoDigests", [])
        if not digests:
            raise HTTPException(status_code=500, detail="No repo digest returned after pull")

        # digests[0] is "image@sha256:..."  — use as-is but restore original tag prefix
        digest = digests[0].split("@")[1]
        pinned = f"{image}:{tag}@{digest}"

        try:
            svc.update(image=pinned)
        except DockerException as e:
            raise HTTPException(status_code=500, detail=f"Service update failed: {e}")

        return {"service": svc.name, "image": pinned, "digest": digest}

    def scale_service(self, name_or_id: str, num: int) -> dict:
        """
        Emulates `docker service scale <name>=<num>`.
        """
        try:
            svc = self._client.services.get(name_or_id)
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service '{name_or_id}' not found")
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        mode_spec = svc.attrs.get("Spec", {}).get("Mode", {})
        if "Global" in mode_spec:
            raise HTTPException(status_code=409, detail="Cannot scale a global mode service")

        try:
            svc.scale(num)
        except DockerException as e:
            raise HTTPException(status_code=500, detail=str(e))

        return {"scaled": svc.name, "id": svc.short_id, "replicas": num}
# ---------------------------------------------------------------------------
# Dependency instances (single-process, no need for DI framework yet)
# ---------------------------------------------------------------------------

_docker_client = DockerClient()
_stack_service = StackService(_docker_client)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/" )
def index():
    return JSONResponse( status_code=302, headers={"Location":"/static/index.html"}, content={} )


@app.get("/stack", response_model=list[dict])
def get_stacks():
    """Return all Docker stacks with their service counts."""
    return _stack_service.list_stacks()

@app.get("/stack/{name}")
def get_stack_services(name: str):
    """Return services in stack"""
    return _stack_service.list_stack_services(name)

@app.delete("/stack/{name}")
def delete_stack(name: str):
    """Remove a stack"""
    return _stack_service.delete_stack(name)




_service_service = ServiceService(_docker_client)

@app.get("/service")
def list_services():
    return _service_service.list_services()

@app.get("/service/{name_or_id}")
def get_service_tasks(name_or_id: str):
    return _service_service.get_service_tasks(name_or_id)

@app.delete("/service/{name_or_id}")
def delete_service(name_or_id: str):
    return _service_service.delete_service(name_or_id)

@app.post("/service/{name_or_id}/rollback")
def rollback_service(name_or_id: str):
    return _service_service.rollback_service(name_or_id)


from pydantic import BaseModel

class ServiceUpdateRequest(BaseModel):
    image: str | None = None

@app.post("/service/{name_or_id}/update")
def update_service(name_or_id: str, body: ServiceUpdateRequest = Body(default=ServiceUpdateRequest())):
    return _service_service.update_service(name_or_id, body.image)

@app.post("/service/{name_or_id}/pull")
def force_pull_update(name_or_id: str):
    return _service_service.force_pull_update(name_or_id)

from fastapi import Path

@app.post("/service/{name_or_id}/scale/{num}")
def scale_service(name_or_id: str, num: int = Path(..., ge=0)):
    return _service_service.scale_service(name_or_id, num)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("swarm_api:app", host="0.0.0.0", port=8080, reload=True )



