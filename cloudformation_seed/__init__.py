from cloudformation_seed import stack_deployer


def main():
    d = stack_deployer.StackDeployer()
    d.run()
