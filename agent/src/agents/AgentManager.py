from .GenericAgent import GenericAgent


class AgentManager:
    def __init__(self):
        self.agents = {
            "generic": GenericAgent(),
        }

    def process(self, prompt: str, agent_type: str = "generic") -> str:
        agent = self.agents.get(agent_type, self.agents["generic"])
        return agent.run(prompt)
