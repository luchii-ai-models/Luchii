export class EmergentAgent {
  constructor(
    private router,
    private memory,
    private identity,
    private orchestrator
  ) {}

  async execute(input: string) {
    const model = this.router.route(input);

    return {
      model,
      response: await this.orchestrator.run(input)
    };
  }
}
