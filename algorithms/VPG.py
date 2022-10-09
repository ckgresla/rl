# Vanilla Policy Gradient (i.e REINFORCE + Baselined Reward)
"""
VPG is commonly "equated" to the REINFORCE, as they are similar "baseline" Policy Optimization Algorithms however I have chosen to implement them separately here as VPG, as introduced in the original paper, mentions/uses the notion of Baselined rewards -- a departure from the regular discounted rewards used to train the older REINFORCE Algorithm. The Folks behind SpinningUp also implement VPG with the GAE, so I will differentiate these (albiet a nitpicky differentiation)

Baselines Implemented: 
1. Normalized Reward
2. Generalized Advantage Estimation (GAE)

Because of this "Baselined" Reward we now need 2 Neural Networks (to approximate 2 functions), a Policy Network (agent's brain) and a Value Network (estimate the reward gradient) -- this is still an on-policy algorithm despite now explicitly implementing a State-Value function, as the thing making decisions (the Policy Network) is the thing that we are altering to change behavior (see the SpinningUp Notes in the "intel" dir for more info)

Reward calculations here also follow the "Rewards-To-Go" model of calculating rewards- https://spinningup.openai.com/en/latest/spinningup/rl_intro3.html#don-t-let-the-past-distract-you -- essentially actions are only reinforced (weights get updated according to the goodness of the action) with the rewards that come AFTER taking the action

"""


import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Categorical




# Class for Algorithm (contains Policy and Value networks as attributes)
class VPG():
    """
    VPG Algorithm as created in:
        Sutton et al. 2000- https://proceedings.neurips.cc/paper/1999/file/464d828b85b0bed98e80ade0a5c43b0f-Paper.pdf

    Parameters:
    - observation_dim: int, number of observations recieved from Environment
    - action_dim: int, number of actions Policy/Agent can take in Environment
    - network_architecture: dict, specification for the structure (layers, activations, optimizer, etc.) of the Policy Network
            Example: {"fc1" : 256, "fc2" : 256, "optimizer" = }  <-- figure out how make (maybe make this a function we call instead?)
    - learning_rate: float, learning rate for Policy Network Optimizer
    - gamma: float, discount rate for reward function
    """
    def __init__(self, policy_net=None, value_net=None):
        super(VPG, self).__init__()
        
        # Algorithm-Environment Info (what types of environments does it work with)
        self.continuous_ok = True
        self.discrete_ok = True

        # Default Hyperparameters -- moved into networks instead
        # self.learning_rate = 0.0002 if learning_rate == None else learning_rate
        # self.gamma = 0.98 if gamma == None else gamma
        # self.lmbda = 0.95 if lmbda == None else lmbda #lambda is a keyword in python, use "lmbda" instead

        # Network Estimators
        self.pi = policy_net
        self.vf = value_net

        # Data Buffer for Episodes
        self.data_keys = ["rewards", "action_probs", "vf_estimate", "normalized_rewards"]
        self.data = {}
        for key in self.data_keys:
            self.data[key] = []

    def append_data(self, name, item):
        """
        add data from environment to buffer for later training
        """
        self.data[name].append(item) #dictionary like; {"data_name" : [list, of, values]}

    def reset_data(self):
        """
        Reset Data store after updating Nets (new buffer for the new data/Networks)
        """
        self.data = {}
        for key in self.data_keys:
            self.data[key] = []
        

    # Calculate Rewards-To-Go (reward gradient only comes from current action/reward & subsequent action/reward pairs, not prior pairs!)
    def rtg(self):
        n_rewards = len(self.data["rewards"]) #number of rewards working with
        rtgs = torch.zeros_like(n_rewards)
        for i in reversed(range(n_rewards)):
            rtgs[i] = self.data["rewards"] + (rtgs[i+1] if i+1 < n_rewards else 0)
        self.data["rewards"] = rtgs #replace standard Episodal Rewards with Rewards-To-Go, inplace (clears out after running optimization)
        return


# Policy Network (pi; observations --> action_logits) 
class PolicyNetwork(nn.Module):
    def __init__(self, observation_dim=4, action_dim=2, learning_rate=1e-4, gamma=.98, lmbda=0.95) -> None:
        super(PolicyNetwork, self).__init__()

        # Input/Output Dimensions for Policy Network (change per environment, default is set to "Cartpole-v1" values)
        self.observation_dim = observation_dim
        self.action_dim = action_dim
        self.learning_rate = learning_rate
        self.gamma = gamma
        self.lmbda = lmbda #lambda is a keyword in python, use "lmbda" instead

        # Policy Network Architecture (given appropriate observation/action | input/output dimensions)
        self.fc1 = nn.Linear(self.observation_dim, 256)
        self.fc2 = nn.Linear(256, self.action_dim)
        self.optimizer = optim.Adam(self.parameters(), lr=self.learning_rate)

    # Forward Pass (given observation, matmul & activate through the network)
    def forward(self, x):
        # x = F.relu(self.fc1(x)) #original Activation in minRL
        x = torch.tanh(self.fc1(x))
        # x = F.softmax(self.fc2(x), dim=0) #original Final Layer (no go as softmax can damage training)
        x = self.fc2(x) #no softmax in the forward pass, want return logits! (instead of probs)
        return x #action_logits (log probabilities, can turn into ACTUAL probabilities with softmax)

    # TODO: GAE GOES IN HERE
    # Reward Function -- estimate the gradient for the Policy Network
    def reward_function(self, data): 
        discounted_reward = 0
        n_timesteps = len(data["rewards"])
        use_advantages = True

        if use_advantages:
            # GAE Calculation
            value_estimates = [i.item() for i in data["vf_estimate"]]
            value_estimates = torch.tensor(value_estimates)

            rewards = torch.tensor(data["rewards"])

            # Calculating Advantage as done in SpinningUp
            # deltas = rewards[:-1] + self.gamma * value_estimates[1:] - value_estimates[:-1]#as listed in spinningup
            # advantages = discount_cumsum(deltas.numpy(), self.gamma * self.lmbda)
            # actionprobs = data['action_probs'] #already should be a tensor
            # actionprobs = actionprobs[:-1]

            advantages = torch.zeros(n_timesteps + 1) #referencing the method in- https://towardsdatascience.com/generalized-advantage-estimate-maths-and-code-b5d5bd3ce737

            for t in reversed(range(n_timesteps)):
                prob_t, r_t, vfe_t, vfe_tm1 = data["action_probs"][t], data["rewards"][t], data["vf_estimate"][t].item(), data["vf_estimate"][t-1].item()
                # delta_t = reward_t + (gamma * vf_estimate_t) <-- CKG Testing delta calc, may not be correct
                # delta_t = data["reward"][t] + (self.gamma * data["vf_estimate"][t-1]) - data["vf_estimate"][t] #below, calls og dict
                delta_t = r_t + (self.gamma * vfe_tm1) - vfe_t
                advantages[t] = delta_t + (self.lmbda * self.gamma + advantages[t+1])

                # loss = -(torch.log(actionprobs) * advantages).mean() #spinningup style
                loss = -torch.log(prob_t) * advantages[t]
                loss.backward()

        else:
            # Normalizing Rewards -- got to work
            reward_tensor = torch.tensor(data["rewards"])
            mu, sigma = torch.mean(reward_tensor), torch.std(reward_tensor)
            data["normalized_rewards"] = (reward_tensor - mu)/(sigma + 1e-10) #add a small epsilon to avoid nans (see- https://stackoverflow.com/questions/49801638/normalizing-rewards-to-generate-returns-in-reinforcement-learning)

            for t in reversed(range(n_timesteps)):
                # Reward Gradients (we got some options here)
                # r_t, prob_t = data["rewards"][t], data["action_probs"][t] #using the actual reward signal for weight update
                r_t, prob_t = data["vf_estimate"][t].item(), data["action_probs"][t] #uses the output of the Value Function to estimate reward
                # r_t, prob_t = data["normalized_rewards"][t].item(), data["action_probs"][t] #uses Normalized Rewards
                discounted_reward = r_t + self.gamma * discounted_reward
                loss = -torch.log(prob_t) * discounted_reward
                loss.backward() #add gradients to each weight in network, parameter update happens in batch, after reward_gradient for the whole Episode (data buffer) is calculated (we call optimizer after the gradients for this performance have been fully set)

    # Run a Sequence of Backprop on the Policy Net
    def parameter_update(self, data):
        """
        Update the Policy Network parameters:
          1. Clear out previous Gradient Values (associated with current network parameters after prev step)
          2. Calculate new Gradients for Episode (estimation of True Gradient, via the reward_function)
          3. Backprop the estimated gradient to the current parameters (update step)
        """
        self.optimizer.zero_grad() #clear out prev gradient
        self.reward_function(data) #estimate reward gradients for prev Episode (adds gradients to network parameters for optimization)
        self.optimizer.step() #backpropagation/update params as per current Gradient


# Value Network Architecture (vf; observations --> vf_estimate)
class ValueNetwork(nn.Module):
    def __init__(self, observation_dim=4, reward_dim=1, learning_rate=1e-4) -> None:
        super(ValueNetwork, self).__init__()

        # Input/Output Dimensions for Policy Network (change per environment, default is set to "Cartpole-v1" values)
        self.observation_dim = observation_dim
        self.reward_dim = reward_dim
        self.learning_rate = learning_rate

        # Value Network Architecture
        self.fc1 = nn.Linear(self.observation_dim, 256)
        self.fc2 = nn.Linear(256, self.reward_dim)
        self.optimizer = optim.Adam(self.parameters(), lr=self.learning_rate)

    # Forward Pass
    def forward(self, x):
        # x = F.relu(self.fc1(x))
        # x = torch.tanh(self.fc1(x))
        x = self.fc1(x)
        x = self.fc2(x)
        return x 

    # Reward Function -- estimate the gradient for the Policy Network
    def reward_function(self, data): 
        discounted_reward = 0
        n_timesteps = len(data["rewards"])

        for t in reversed(range(n_timesteps)):
            r_t, pred_t = torch.tensor([data["rewards"][t]]), data["vf_estimate"][t] #make the actual reward (float) a tensor for error calculation
            reward_delta = torch.nn.functional.mse_loss(r_t, pred_t) #loss for value function
            loss = reward_delta
            loss.backward() #add the calculated grads to the Value Network Params
    
    # Run a Sequence of Backprop on the Policy Net
    def parameter_update(self, data):
        """
        Update the Policy Network parameters:
          1. Clear out previous Gradient Values (associated with current network parameters after prev step)
          2. Calculate new Gradients for Episode (estimation of True Gradient, via the reward_function)
          3. Backprop the estimated gradient to the current parameters (update step)
        """
        self.optimizer.zero_grad() #clear out prev gradient
        self.reward_function(data) #estimate reward gradients for prev Episode (adds gradients to network parameters for optimization)
        self.optimizer.step() #backpropagation/update params as per current Gradient




# this function needs to be moved into the `reports` util in the "core" dir
def print_info(n_episodes, print_interval, score=0):
    """
    standardized string for printing training information (handle when to log/print logic in main script)
    how incorporate different metrics here?
    """
    avg_score = f"{score/print_interval:.2f}"
    print(f"Episode {n_episodes: ^{10}}", end="    ")
    # cp(f"Avg Score {avg_score: ^{10}}", color="red") #need import color print from the "core.reports" module
    print(f"Avg Score {avg_score: ^{10}}")
    return

# implement here for now, potentially move into interaction later (if feels better there)
def sd_sampler(action_logits):
    """
    Stochastic Discrete Action Sample Wrapper
    - Samples Actions & corresponding Probability from the PyTorch Categorical/Multinomial Distribution- https://pytorch.org/docs/stable/distributions.html#distribution

    input is the RAW logits from the output of the network (computes probabilities with Softmax under the hood)
        return is the; int for the action sampled & the Probability associated with that action
    """
    # action_logits = torch.nan_to_num(action_logits, nan=-.1, posinf=0.1)
    probs = torch.nn.functional.softmax(action_logits, dim=0) #convert Network outputted logits into Probabilties
    action_distribution = Categorical(probs=probs) #instantiate distribution with action probabilities (not logits, although COULD do that too)
    action = action_distribution.sample() #returns an int for the sampled action
    action_prob = probs[action] #likelihood of making this action as per the policy (logp)

    return action.item(), action_prob

# Discounted CumSum from SpinningUp/Ray- https://github.com/openai/spinningup/blob/038665d62d569055401d91856abb287263096178/spinup/algos/pytorch/vpg/core.py#L29
def discount_cumsum(x, discount):
    """
    magic from rllab for computing discounted cumulative sums of vectors.

    input:
        vector x,
        [x0,
         x1,
         x2]

    output:
        [x0 + discount * x1 + discount^2 * x2,
         x1 + discount * x2,
         x2]
    """
    import scipy.signal
    print(x)
    print(discount)
    return scipy.signal.lfilter([1], [1, float(-discount)], x[::-1], axis=0)[::-1]


# Run Algorithm on Cartpole as Example
def cartpole_test(num_epochs=10000, num_episodes=1):
    import gym

    env = gym.make('CartPole-v1')
    # Defaults to Cartpole Dims in Both Networks
    # pi = PolicyNetwork()
    pi = PolicyNetwork(learning_rate=0.0002, gamma=0.98)
    vf = ValueNetwork()
    vpg = VPG(pi, vf) #has both an Policy and Value Network

    # Performing a Optimization Step per Episode (unlike the batched SpinningUp Implementation)
    for epoch in range(num_epochs):
        epoch_reward = 0.0
        vf_error = 0.0
        for episode in range(num_episodes):
            s = env.reset()
            done = False

            while not done: 
                # env.render() #human viz of training process

                # Get Action from Logits (after forward pass w Policy Network)
                obs = torch.from_numpy(s).float() #convert state given from Env into torch vec for passing to network (observation)
                logits = vpg.pi(obs) #forward pass, computes action logits with Policy Network
                # print(f"logits {logits}\n  for obs {obs}")
                action, prob_a = sd_sampler(logits) #sample action (int) and get corresponding probabilties (from stochastic dist.)

                # Value Function Reward Estimate
                vf_estimate = vpg.vf(obs)

                # Interaction Step w Environment (say at; timestep t)
                state_t_1, reward_t, done, info = env.step(action) #recieve next state (t+1) and reward for taken action (reward at timestep t)
                
                # Append Data to Buffer + Track State/Rewards
                vpg.append_data("rewards", reward_t) #append the reward for the current step to buffer
                vpg.append_data("action_probs", prob_a) #append the probability of the taken action for the current step to buffer
                vpg.data["vf_estimate"].append(vf_estimate)
                s = state_t_1 #next/new state is now the current state
                # episode_reward += reward_t #episode reward
                epoch_reward += reward_t #episode reward
                vf_error += -1*(vf_estimate.item() - reward_t)

            # SpinningUp Style Metrics
            # episode_return, episode_len = sum(vpg.data["rewards"]), len(vpg.data["rewards"])
            #may not need this rtg call.... (already computing the rewards to go)
            # vpg.rtg() #computes rewards to go (references the "self.data" buffer & alters the ["reward"] list of values)

        vpg.pi.parameter_update(vpg.data) #after termination of episode, update the policy
        vpg.vf.parameter_update(vpg.data) #after termination of episode, update the Value Function
        vpg.reset_data() #clear out data buffer after training Networks

        # Print Info per N Trajectories (episodes of running a specific Policy)
        # if n_epi%print_interval==0 and n_epi!=0:
            # print("Episode {}\tavg_score {}".format(n_epi, score/print_interval)) #original print statement
            # print_info(n_epi, print_interval, episode_reward)
            # episode_reward = 0.0 #reset reward for tracking next sequence
        if epoch % 100 == 0:
            print(f"Epoch {epoch}    avg_score {epoch_reward/num_episodes:.0f}    VF Error {vf_error/num_episodes:.3f}")

    env.close()


# Sample Run of Algorithm
if __name__ == '__main__':
    cartpole_test()
