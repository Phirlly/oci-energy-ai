# OCI Energy AI

A hands-on lab for exploring how AI can help explain electricity costs.
Start with a prepared office example, try a battery scenario, then review your
own electricity bills—all in a browser.

## What you'll try

- **Understand a bill:** see electricity use, peak demand and the charges behind
  a sample office bill.
- **Try a battery:** change its size and see how it could affect the modeled bill.
- **Ask the analysts:** get explanations from two AI analysts and inspect the
  calculations they used.
- **Review your own bills:** check extracted facts, correct them and compare
  usage and costs across the periods you provide.

The app runs on OCI. The [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents/sdk)
runs the analysts and their calculation tools, using your selected OCI, OpenAI
or Anthropic model. The calculations work without AI; model access enables
the explanations and optional bill extraction.

## Deploy on OCI

**Preview:** fresh Resource Manager installation is still being validated.

<p align="center">
  <a href="https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https%3A%2F%2Fobjectstorage.us-ashburn-1.oraclecloud.com%2Fn%2Fiddpyrbvyjar%2Fb%2Foci-energy-ai-releases-5d7383358dbb-artifacts%2Fo%2Ftemplates%252F94f711f0aa3cf27b24ec5bb753b1334fa0cdb634977108a6f642192e9bba70ad.zip">
    <img src="https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg" alt="Deploy to Oracle Cloud">
  </a>
</p>

You'll need an OCI account with permission to create the demo's resources.
Hosting and model usage incur charges. This deployment path needs no GitHub
configuration or local tools.

Follow [DEMO.md](DEMO.md) for the deployment steps, browser setup and a guided
walkthrough. Optional local and GitHub instructions are there too.

## About the example

The [office sample](examples/monthly-office/README.md) uses public modeled
building data and an invented tariff. Battery results illustrate operating-cost
changes; they are not equipment investment advice. Your bills can support usage
and cost comparisons, but monthly totals alone cannot establish battery savings.
