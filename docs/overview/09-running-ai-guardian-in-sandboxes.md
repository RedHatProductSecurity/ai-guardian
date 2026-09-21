# Running AI Guardian in Sandboxes: Docker, Podman, and OpenShell

*A practical guide to choosing a sandbox runtime and understanding what isolation changes for AI-assisted development.*

Running an AI coding agent inside a sandbox changes the boundary around the work. Instead of giving the agent direct access to a broad host environment, the project can be placed in a managed runtime with its own filesystem, network policy, configuration snapshot, and lifecycle.

AI Guardian supports both conventional container runtimes and OpenShell. The right choice depends on the environment, the isolation requirements, and the operational tools available to the team.

## Docker and Podman

The container runtime is the straightforward option for teams already using Docker or Podman. A prebuilt AI Guardian image can include the daemon, scanners, and supported headless agent integrations. A repository can be mounted into the container, and ports can be mapped when a console or daemon endpoint needs to be reached from the host.

Podman is the default container engine in many AI Guardian examples, while Docker can be selected through the container-engine setting. The important operational questions are familiar ones: who owns the image, what directories are mounted, what credentials are present inside the container, and how the container is updated and removed.

Mount only the repository and data the task requires. A container boundary does not automatically make every mounted file safe. If a credential or host directory is made available to the agent, the agent may still be able to read it unless an additional policy prevents access.

## OpenShell

OpenShell provides a more policy-oriented sandbox model. The gateway can keep provider credentials outside the agent sandbox and apply network and filesystem restrictions per sandbox. This can make OpenShell a stronger choice when isolation and credential separation are central requirements.

The integration is still evolving, so compatibility should be checked before important work. The runtime, CLI, gateway, image, selected agent, and provider authentication all participate in the result.

## Creating a sandbox

The sandbox command is the supported entry point for lifecycle management. A conceptual container-runtime example looks like this:

```bash
ai-guardian sandbox create \
  --runtime container \
  --name guardian-project \
  --repo /path/to/repository
```

OpenShell uses the corresponding runtime selection and requires an OpenShell CLI connected to a gateway. The exact options should be taken from the current documentation for the installed version.

After creation, the normal lifecycle is:

1. Inspect the sandbox and its status.
2. Connect to it or execute a controlled command.
3. Run the selected agent inside the prepared environment.
4. Review logs and security findings.
5. Stop or restart the sandbox when the work pauses.
6. Remove it when its data is no longer needed.

## Choosing between runtimes

Choose Docker or Podman when simplicity, local familiarity, and broad container tooling are the priorities. Choose OpenShell when gateway-managed credentials, stronger network and filesystem policy, and per-sandbox isolation are more important.

In both cases, sandboxing complements AI Guardian’s scanning and policy checks. It does not eliminate the need for secret scanning, directory rules, tool permissions, or review of the agent’s changes.

## The tradeoff is visibility versus isolation

Moving work into a sandbox can improve isolation, but it also introduces operational questions. Where are logs stored? How does a developer reach the Console? Which configuration snapshot was used? How are repository changes returned to the host? What happens to temporary data when the sandbox is removed?

These questions should be answered before a team treats a sandbox as a complete security solution. A tightly isolated environment that nobody can monitor is difficult to operate responsibly. Conversely, a convenient container with broad mounts and host credentials may provide less protection than its name suggests.

The strongest deployments combine runtime isolation with AI Guardian’s policy checks and ordinary platform controls. The runtime limits the environment; AI Guardian evaluates the agent’s behavior inside it; the team reviews the resulting changes and operational evidence.

Read more: [Sandbox CLI](https://ai-guardian.readthedocs.io/en/latest/Sandbox/), [Container Image](https://ai-guardian.readthedocs.io/en/latest/project/container/), and [Security Design](https://ai-guardian.readthedocs.io/en/latest/SECURITY_DESIGN/).
