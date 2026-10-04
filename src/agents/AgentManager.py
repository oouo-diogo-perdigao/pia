from .GenericAgent import GenericAgent


class AgentManager:
    def __init__(self):
        self.agents = {
            "generic": GenericAgent(),
        }

    def process(self, prompt: str, agent_type: str = "generic") -> str:
        agent = self.agents.get(agent_type, self.agents["generic"])
        return agent.run(prompt)

    def process_stream(self, prompt: str, agent_type: str = "generic"):
        agent = self.agents.get(agent_type, self.agents["generic"])
        if hasattr(agent, "run_stream"):
            yield from agent.run_stream(prompt)
        else:
            yield agent.run(prompt)
