import matplotlib.pyplot as plt
import numpy as np
np.arange(0,1,0.1)
loads = [0.1, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95]
xaxis = np.arange(0, 1.1, 0.1)

response_random = [162.065638742, 234.915390306, 358.092913426, 550.860145323, 730.894938963, 888.090919257, 921.455768435]
response_per_task = [160.475727526, 162.575389521, 175.309317597, 244.683165513, 274.306029817, 322.291425626, 351.843694002]
response_batch = [164.988566003, 157.812765627, 161.990262703, 185.491760669, 239.000155853, 282.075505067, 334.35613782]
response_sparrow = [162.963706227, 160.106357934, 162.916128574, 165.531015798, 166.51307071, 175.783487169, 209.8024248]

# plt.plot(loads, response_random, 'r--')
plt.plot(loads, response_random, 'r--', loads, response_per_task, 'b--', loads, response_batch, 'g--', loads, response_sparrow, 'g*-')
# plt.axis(xaxis)
plt.show()