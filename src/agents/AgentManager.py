from .GenericAgent import GenericAgent


class AgentManager:
    def __init__(self):
        self.agents = {
            "generic": GenericAgent(),
        }

    def process(
        self, prompt: str, agent_type: str = "generic", model: str | None = None
    ) -> str:
        agent = self.agents.get(agent_type, self.agents["generic"])
        return agent.run(prompt, model=model)

    def process_stream(
        self, prompt: str, agent_type: str = "generic", model: str | None = None
    ):
        agent = self.agents.get(agent_type, self.agents["generic"])
        if hasattr(agent, "run_stream"):
            yield from agent.run_stream(prompt, model=model)
        else:
            yield agent.run(prompt, model=model)

    def complete(self, messages, model=None, **options):
        return self.agents["generic"].complete(messages, model, **options)

    def complete_stream(self, messages, model=None, **options):
        yield from self.agents["generic"].complete_stream(messages, model, **options)
